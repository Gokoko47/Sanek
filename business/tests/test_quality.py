import concurrent.futures
import copy
import dataclasses
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from business.bot import BusinessBot, Config, Store, OpenAI, APIError, NOTICE
from business.bot_types import is_sensitive
from business.scheduler import QuietScheduler
from business.voice import VoiceRecognizer

OWNER=100
PEER=200
CID='quality-connection'


class Clock:
    def __init__(self):self.wall=1_800_000_000.;self.mono=100.
    def now(self):return self.wall
    def monotonic(self):return self.mono
    def advance(self,n):self.wall+=n;self.mono+=n


class Scheduler:
    def __init__(self,clock):self.clock=clock;self.jobs={};self.closed=False
    def schedule(self,key,delay,callback):self.jobs[key]=(self.clock.monotonic()+delay,callback)
    def cancel(self,key):self.jobs.pop(key,None)
    def cancel_all(self):self.jobs.clear()
    def close(self):self.closed=True;self.cancel_all()
    def fire(self):
        for key,(due,callback) in list(self.jobs.items()):
            if due<=self.clock.monotonic() and key in self.jobs:
                self.jobs.pop(key);callback()


class Executor:
    def __init__(self):self.deferred=False;self.jobs=[]
    def submit(self,fn,*args):
        if self.deferred:self.jobs.append((fn,args))
        else:fn(*args)
    def finish(self):
        while self.jobs:
            fn,args=self.jobs.pop(0);fn(*args)
    def shutdown(self,**kwargs):self.jobs.clear()


class Telegram:
    def __init__(self,clock):
        self.clock=clock;self.calls=[];self.next=1000;self.hook=None
        self.connection={'id':CID,'user':{'id':OWNER},'is_enabled':True,'rights':{'can_reply':True}}
    def call(self,method,**params):
        self.calls.append((method,copy.deepcopy(params)))
        if self.hook:self.hook(method,params)
        if method=='getBusinessConnection':return copy.deepcopy(self.connection)
        if method=='getWebhookInfo':return {'url':''}
        if method=='getMe':return {'id':900,'can_connect_to_business':True}
        if method=='sendMessage':
            self.next+=1;return {'message_id':self.next,'date':int(self.clock.now())}
        return True
    def business(self):return [p for m,p in self.calls if m=='sendMessage' and 'business_connection_id' in p]
    def owner(self):return [p for m,p in self.calls if m=='sendMessage' and 'business_connection_id' not in p]


class AI:
    def __init__(self):self.calls=[];self.hook=None;self.result='да норм, ты как'
    def reply(self,text,style,examples=None,context=None):
        self.calls.append(copy.deepcopy({'text':text,'style':style,'examples':examples,'context':context}))
        if self.hook:self.hook()
        return self.result


class Voice:
    def __init__(self):self.calls=[];self.hook=None;self.text='как у тебя дела'
    def transcribe(self,media):
        self.calls.append(media)
        if self.hook:self.hook()
        return self.text


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.scheduler=Scheduler(self.clock);self.executor=Executor()
        self.api=Telegram(self.clock);self.ai=AI();self.voice=Voice();self.store=Store(':memory:')
        self.config=Config(bot_token='123:'+'x'*30,owner_id=OWNER,openai_key='test',db_path=':memory:',cooldown_seconds=0)
        self.bot=BusinessBot(self.config,self.api,self.ai,self.store,self.executor,self.clock.now,
            scheduler=self.scheduler,monotonic=self.clock.monotonic,voice=self.voice)
    def tearDown(self):self.bot.close();self.store.db.close()
    def incoming(self,mid,text='привет',peer=PEER,**fields):
        m={'business_connection_id':CID,'message_id':mid,'date':int(self.clock.now()),'from':{'id':peer},'chat':{'id':peer,'type':'private','first_name':'Тестовый собеседник'},'text':text}
        m.update(fields);return {'business_message':m}
    def send(self,mid,text='привет',peer=PEER,**fields):self.bot.handle(self.incoming(mid,text,peer,**fields))
    def flush(self,n=6):self.clock.advance(n);self.scheduler.fire()
    def command(self,text,actor=OWNER,reply=None):
        m={'chat':{'id':actor,'type':'private'},'from':{'id':actor},'text':text}
        if reply is not None:m['reply_to_message']={'message_id':reply}
        self.bot.handle({'message':m})
    def token(self,action,**values):return self.store.issue_control(OWNER,{'action':action,**values},self.clock.now())
    def click(self,data,actor=OWNER,chat=OWNER):
        self.bot.handle({'callback_query':{'id':'callback-test','from':{'id':actor},'message':{'chat':{'id':chat,'type':'private'}},'data':data}})
    def draft(self):return dict(self.store.db.execute('SELECT * FROM reply_drafts ORDER BY rowid DESC LIMIT 1').fetchone())

    def test_quiet_window_combines_burst_once(self):
        self.send(1,'привет');self.clock.advance(2);self.send(2,'как дела');self.clock.advance(2);self.send(3,'что нового')
        self.flush(5);self.assertFalse(self.ai.calls)
        self.flush(1);self.assertEqual(len(self.ai.calls),1);self.assertEqual(self.ai.calls[0]['text'],'привет\nкак дела\nчто нового')
        self.assertEqual(len(self.api.business()),1);self.assertEqual(self.api.business()[0]['reply_parameters']['message_id'],3)
    def test_continuous_burst_has_maximum_wait(self):
        for i in range(1,6):self.send(i,'строка '+chr(64+i));self.clock.advance(4);self.scheduler.fire()
        self.assertEqual(len(self.api.business()),1)
    def test_timer_is_not_wall_clock_based(self):
        self.send(1);deadline=self.scheduler.jobs[(CID,PEER)][0];self.clock.wall-=60
        self.assertEqual(deadline,106);self.assertEqual(self.scheduler.jobs[(CID,PEER)][0],deadline)
    def test_chats_are_batched_independently(self):
        self.send(1,'первый',PEER);self.clock.advance(1);self.send(2,'второй',201)
        self.flush(5);self.assertEqual(len(self.api.business()),1)
        self.flush(1);self.assertEqual({m['chat_id'] for m in self.api.business()},{200,201})
    def test_old_timer_cannot_flush_new_generation(self):
        self.send(1);old=self.scheduler.jobs[(CID,PEER)][1]
        self.clock.advance(1);self.send(2);old();self.assertFalse(self.api.business())
        self.flush();self.assertEqual(len(self.api.business()),1)
    def test_manual_reply_cancels_burst_and_becomes_context(self):
        self.send(1);self.send(2,'я отвечу сам',**{'from':{'id':OWNER}});self.flush()
        self.assertFalse(self.ai.calls)
        rows=self.bot.history.snapshot(CID,PEER,set(),self.clock.now())
        self.assertIn({'role':'assistant','text':'я отвечу сам'},rows)
    def test_backlog_owner_reply_does_not_pause_new_chat(self):
        self.send(1,'старое',date=int(self.clock.now())-100,**{'from':{'id':OWNER}})
        self.send(2);self.flush();self.assertEqual(len(self.api.business()),1)
    def test_stop_before_restart_is_still_honored(self):
        self.send(1,'/stop',date=int(self.clock.now())-1000);self.send(2);self.flush();self.assertFalse(self.ai.calls)
    def test_deleting_first_message_cancels_entire_burst(self):
        self.send(1,'первая');self.send(2,'вторая')
        self.bot.handle({'deleted_business_messages':{'business_connection_id':CID,'chat':{'id':PEER},'message_ids':[1]}})
        self.flush();self.assertFalse(self.ai.calls);self.assertEqual(self.bot.history.snapshot(CID,PEER,set(),self.clock.now()),[])
    def test_editing_source_cancels_queued_reply(self):
        self.send(1)
        self.bot.handle({'edited_business_message':self.incoming(1,'другое')['business_message']})
        self.flush();self.assertFalse(self.api.business())
    def test_global_pause_cancels_all_timers(self):
        self.send(1);self.send(2,peer=201);self.command('/pause');self.flush();self.assertFalse(self.ai.calls)
    def test_disconnect_clears_memory_and_pending(self):
        self.send(1);self.bot.handle({'business_connection':{**self.api.connection,'is_enabled':False}})
        self.flush();self.assertFalse(self.ai.calls);self.assertEqual(self.bot.history.snapshot(CID,PEER,set(),self.clock.now()),[])
    def test_sensitive_fragment_in_burst_prevents_any_reply(self):
        self.send(1,'вот мой');self.send(2,'пароль');self.send(3,'обычный текст');self.flush()
        self.assertFalse(self.ai.calls);self.assertTrue(self.store.chat(CID,PEER)['needs_review'])
    def test_combined_sensitive_words_are_reviewed(self):
        self.send(1,'код');self.send(2,'входа');self.flush();self.assertFalse(self.ai.calls)
    def test_review_notifications_are_not_spammed(self):
        self.send(1,'пароль');self.send(2,'пароль');self.send(3,'пароль')
        notices=[p for p in self.api.owner() if p['text'].startswith('Нужен ручной')]
        self.assertEqual(len(notices),1);self.assertNotIn('пароль',notices[0]['text'])
    def test_burst_overflow_fails_to_manual_not_partial_reply(self):
        for i in range(1,14):self.send(i,'привет')
        self.flush();self.assertFalse(self.ai.calls);self.assertTrue(self.store.chat(CID,PEER)['needs_review'])
    def test_context_contains_prior_exchange_not_current_batch(self):
        self.send(1,'как настроение');self.flush();self.send(2,'а у тебя');self.flush()
        context=self.ai.calls[-1]['context']
        self.assertIn({'role':'user','text':'как настроение'},context)
        self.assertIn({'role':'assistant','text':self.ai.result},context)
        self.assertNotIn({'role':'user','text':'а у тебя'},context)
    def test_context_never_crosses_chats(self):
        self.send(1,'текст для первого');self.flush();self.send(2,'текст для второго',201);self.flush()
        self.assertEqual(self.ai.calls[-1]['context'],[])
    def test_context_expires(self):
        self.bot.history.remember(CID,PEER,1,'user','старый контекст',self.clock.now())
        self.clock.advance(86401);self.assertEqual(self.bot.history.snapshot(CID,PEER,set(),self.clock.now()),[])
    def test_context_limits_message_count_and_characters(self):
        self.bot.history.max_messages=3;self.bot.history.max_chars=500
        for i in range(8):self.bot.history.remember(CID,PEER,i,'user','a'*180,self.clock.now()+i)
        rows=self.bot.history.snapshot(CID,PEER,set(),self.clock.now()+8)
        self.assertLessEqual(len(rows),3);self.assertLessEqual(sum(len(r['text']) for r in rows),500)
    def test_context_global_limit(self):
        for i in range(505):self.bot.history.remember(CID,1000+i,i,'user','a',self.clock.now()+i)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM conversation_context').fetchone()[0],500)
    def test_context_can_be_disabled_and_cleared(self):
        self.send(1);self.flush();self.click(self.token('memory_toggle'));self.send(2);self.flush()
        self.assertFalse(self.bot.history.enabled());self.assertEqual(self.ai.calls[-1]['context'],[])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM conversation_context').fetchone()[0],0)
    def test_context_clear_cancels_already_running_result(self):
        self.ai.hook=lambda:self.command('/clearcontext')
        self.send(1);self.flush();self.assertFalse(self.api.business())
        self.assertEqual(self.bot.history.snapshot(CID,PEER,set(),self.clock.now()),[])
    def test_friendly_year_is_not_treated_as_login_code(self):
        self.assertFalse(is_sensitive('в 2026 году хорошо погуляли'))
        self.assertTrue(is_sensitive('1234'));self.assertTrue(is_sensitive('sk-'+('a'*30)))
    def test_owner_menu_has_bounded_callback_data(self):
        self.command('/menu');keyboard=self.api.owner()[-1]['reply_markup']['inline_keyboard']
        self.assertGreater(len(keyboard),2)
        self.assertTrue(all(len(b['callback_data'].encode())<=64 for row in keyboard for b in row))
    def test_nonowner_cannot_use_or_consume_control(self):
        token=self.token('pause');self.click(token,actor=201);self.assertFalse(self.store.paused())
        self.click(token);self.assertTrue(self.store.paused())
    def test_forwarded_menu_cannot_act_in_another_chat(self):
        token=self.token('pause');self.click(token,chat=201);self.assertFalse(self.store.paused())
    def test_callback_is_single_use(self):
        token=self.token('pause');self.click(token);self.command('/resume');self.click(token)
        self.assertFalse(self.store.paused())
    def test_expired_button_does_not_act(self):
        token=self.token('pause');self.clock.advance(901);self.click(token);self.assertFalse(self.store.paused())
    def test_per_chat_mode_does_not_change_another(self):
        self.send(1);self.send(2,peer=201)
        self.click(self.token('mode',cid=CID,chat=PEER,value='off'));self.flush()
        self.assertEqual([x['chat_id'] for x in self.api.business()],[201])
    def test_chat_style_can_differ_from_global(self):
        self.send(1);self.store.chat_style(CID,PEER,'официально, кратко');self.bot.cancel(CID,PEER)
        self.send(2);self.flush();self.assertEqual(self.ai.calls[-1]['style'],'официально, кратко')
    def test_style_form_is_bound_to_owners_reply(self):
        self.click(self.token('ask_style'));prompt=self.api.next
        self.command('новый стиль',actor=201,reply=prompt);self.assertEqual(self.store.get('style',''),'')
        self.command('коротко и дружелюбно',reply=prompt);self.assertEqual(self.store.get('style'),'коротко и дружелюбно')
    def test_unrelated_owner_text_does_not_change_style(self):
        self.click(self.token('ask_style'));self.command('случайное сообщение');self.assertEqual(self.store.get('style',''),'')
    def test_delay_setting_survives_new_instance(self):
        self.command('/delay 10');self.assertEqual(self.store.get('debounce_seconds'),'10.0')
        self.assertEqual(self.bot.delay(),10)
    def test_bad_delay_is_rejected(self):
        self.command('/delay nan');self.assertEqual(self.bot.delay(),6)
        self.command('/delay -1');self.assertEqual(self.bot.delay(),6)
    def test_voice_requires_explicit_enable(self):
        self.send(1,'',voice={'file_id':'file','duration':10});self.flush();self.assertFalse(self.voice.calls)
    def test_voice_is_transcribed_then_batched_with_text(self):
        self.store.set('voice_enabled','1');self.send(1,'',voice={'file_id':'file','duration':10})
        self.send(2,'и ещё привет');self.flush()
        self.assertEqual(len(self.voice.calls),1);self.assertEqual(self.ai.calls[0]['text'],'как у тебя дела\nи ещё привет')
    def test_sensitive_transcript_never_reaches_chat_model(self):
        self.store.set('voice_enabled','1');self.voice.text='Мой пароль 123456'
        self.send(1,'',voice={'file_id':'file','duration':10});self.flush()
        self.assertFalse(self.ai.calls);self.assertFalse(self.api.business())
    def test_stop_during_transcription_cancels_generation(self):
        self.store.set('voice_enabled','1');self.voice.hook=lambda:self.command('/pause')
        self.send(1,'',voice={'file_id':'file','duration':10});self.flush();self.assertFalse(self.ai.calls)
    def test_long_voice_is_not_downloaded(self):
        self.store.set('voice_enabled','1');self.send(1,'',voice={'file_id':'file','duration':301})
        self.flush();self.assertFalse(self.voice.calls)
    def test_ai_budget_prevents_more_provider_requests(self):
        self.bot.config=dataclasses.replace(self.config,max_ai_requests_per_hour=1)
        self.send(1);self.flush();self.send(2);self.flush();self.assertEqual(len(self.ai.calls),1)
    def test_assistant_draft_needs_owner_confirmation(self):
        self.send(1);self.store.mode(CID,PEER,'assist');self.bot.cancel(CID,PEER);self.send(2);self.flush()
        self.assertFalse(self.api.business());d=self.draft()
        self.click(self.token('send_draft',draft=d['id'],revision=0));self.assertEqual(len(self.api.business()),1)
    def test_new_message_invalidates_old_draft(self):
        self.send(1);self.store.mode(CID,PEER,'assist');self.bot.cancel(CID,PEER);self.send(2);self.flush();d=self.draft()
        self.send(3);self.click(self.token('send_draft',draft=d['id'],revision=0));self.assertFalse(self.api.business())
    def test_double_approval_sends_once(self):
        self.send(1);self.store.mode(CID,PEER,'assist');self.bot.cancel(CID,PEER);self.send(2);self.flush();d=self.draft()
        for _ in range(2):self.click(self.token('send_draft',draft=d['id'],revision=0))
        self.assertEqual(len(self.api.business()),1)
    def test_edit_is_previewed_before_sending_and_can_teach(self):
        self.send(1);self.store.mode(CID,PEER,'assist');self.bot.cancel(CID,PEER);self.send(2);self.flush();d=self.draft()
        self.click(self.token('edit_draft',draft=d['id'],revision=0));prompt=self.api.next
        self.command('здарова, всё ок',reply=prompt);self.assertFalse(self.api.business())
        self.click(self.token('send_teach',draft=d['id'],revision=1));self.assertEqual(len(self.api.business()),1)
        self.assertEqual(self.store.examples()[0]['owner_reply'],'здарова, всё ок')
    def test_unedited_model_output_cannot_teach_personality(self):
        self.send(1);self.store.mode(CID,PEER,'assist');self.bot.cancel(CID,PEER);self.send(2);self.flush();d=self.draft()
        self.click(self.token('send_teach',draft=d['id'],revision=0));self.assertFalse(self.api.business());self.assertFalse(self.store.examples())
    def test_old_revision_cannot_send_or_dismiss_new_edit(self):
        self.send(1);self.store.mode(CID,PEER,'assist');self.bot.cancel(CID,PEER);self.send(2);self.flush();d=self.draft()
        self.bot.drafts.revise(d['id'],'другой ответ',0,self.clock.now())
        self.click(self.token('send_draft',draft=d['id'],revision=0));self.assertFalse(self.api.business())
        self.click(self.token('dismiss_draft',draft=d['id'],revision=0));self.assertEqual(self.bot.drafts.get(d['id'],self.clock.now())['state'],'pending')
    def test_delivery_failure_is_not_retried_by_another_button(self):
        self.send(1);self.store.mode(CID,PEER,'assist');self.bot.cancel(CID,PEER);self.send(2);self.flush();d=self.draft()
        def fail(method,params):
            if method=='sendMessage' and 'business_connection_id' in params:raise APIError(502)
        self.api.hook=fail
        for _ in range(2):self.click(self.token('send_draft',draft=d['id'],revision=0))
        self.assertEqual(len(self.api.business()),1)
    def test_clear_context_also_removes_pending_drafts(self):
        self.send(1);self.store.mode(CID,PEER,'assist');self.bot.cancel(CID,PEER);self.send(2);self.flush();d=self.draft()
        self.command('/clearcontext');self.assertIsNone(self.bot.drafts.get(d['id'],self.clock.now()))
    def test_delivery_ack_after_context_clear_cannot_restore_memory(self):
        def clear(method,params):
            if method=='sendMessage' and 'business_connection_id' in params:self.bot.clear_context()
        self.api.hook=clear;self.send(1);self.flush()
        self.assertEqual(self.bot.history.snapshot(CID,PEER,set(),self.clock.now()),[])


class InfrastructureTests(unittest.TestCase):
    def test_scheduler_replaces_and_shuts_down(self):
        scheduler=QuietScheduler();old=threading.Event();latest=threading.Event()
        try:
            scheduler.schedule('chat',100,old.set);scheduler.schedule('chat',0,latest.set)
            self.assertTrue(latest.wait(2));self.assertFalse(old.is_set())
        finally:scheduler.close()
        self.assertFalse(scheduler.thread.is_alive())
    def test_scheduler_cancel_drops_long_wait(self):
        scheduler=QuietScheduler();event=threading.Event();scheduler.schedule('chat',100,event.set);scheduler.cancel('chat');scheduler.close()
        self.assertFalse(event.is_set());self.assertFalse(scheduler.thread.is_alive())
    def test_scheduler_heap_is_bounded_after_many_reschedules(self):
        scheduler=QuietScheduler()
        try:
            for _ in range(1000):scheduler.schedule('chat',100,lambda:None)
            with scheduler.condition:self.assertLessEqual(len(scheduler.heap),70)
        finally:scheduler.close()
    def test_sqlite_migration_preserves_old_state(self):
        with tempfile.TemporaryDirectory() as temp:
            path=temp+'/old.sqlite3';db=sqlite3.connect(path)
            db.executescript('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL); INSERT INTO meta VALUES ("style","мой стиль"); CREATE TABLE chats(connection TEXT,chat INTEGER,latest INTEGER DEFAULT 0,generation INTEGER DEFAULT 0,paused_until REAL DEFAULT 0,stopped INTEGER DEFAULT 0,notified INTEGER DEFAULT 0,last_sent REAL DEFAULT 0,PRIMARY KEY(connection,chat)); INSERT INTO chats(connection,chat,latest,stopped) VALUES ("c",200,5,1);');db.close()
            store=Store(path)
            try:self.assertEqual(store.get('style'),'мой стиль');self.assertEqual(store.chat('c',200)['stopped'],1);self.assertEqual(store.chat('c',200)['mode'],'auto')
            finally:store.db.close()
    def test_bad_numeric_settings_fail_without_echoing_value(self):
        values={'TELEGRAM_BOT_TOKEN':'123:'+'x'*30,'TELEGRAM_OWNER_ID':'secret-value'}
        with self.assertRaises(ValueError) as error:Config.env(values)
        self.assertNotIn('secret-value',str(error.exception))
    def test_nan_and_unbounded_memory_config_rejected(self):
        for key,value in [('DEBOUNCE_SECONDS','nan'),('CONTEXT_MAX_CHARS','999999'),('VOICE_MAX_BYTES','999999999')]:
            with self.assertRaises(ValueError):Config.env({'TELEGRAM_BOT_TOKEN':'123:'+'x'*30,key:value})
    def test_provider_context_stays_untrusted_data(self):
        provider=OpenAI(Config(bot_token='fake',openai_key='test'))
        response={'choices':[{'message':{'content':'{"action":"reply","reply":"привет"}'}}]}
        context=[{'role':'assistant','text':'предыдущий ответ'}]
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as network:
            provider.reply('привет','коротко',[],context)
            messages=json.loads(network.call_args.args[0].data)['messages']
            self.assertEqual([m['role'] for m in messages],['system','user'])
            self.assertEqual(json.loads(messages[1]['content'])['recent_context'],context)
    def test_json_array_from_provider_fails_closed(self):
        provider=OpenAI(Config(bot_token='fake'))
        response={'choices':[{'message':{'content':'[]'}}]}
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
            self.assertIsNone(provider.reply('привет','коротко'))
    def test_voice_transcription_has_fixed_filename(self):
        api=type('API',(),{'download':lambda self,id,limit:b'OggS-example'})()
        voice=VoiceRecognizer(Config(bot_token='fake',openai_key='test'),api)
        with patch('urllib.request.urlopen',return_value=io.BytesIO('{"text":"привет"}'.encode())) as network:
            self.assertEqual(voice.transcribe({'file_id':'file','duration':3}),'привет')
            self.assertIn(b'filename="voice.ogg"',network.call_args.args[0].data)
    def test_voice_download_error_does_not_call_provider(self):
        api=type('API',(),{'download':lambda *args:(_ for _ in ()).throw(APIError(502))})()
        with patch('urllib.request.urlopen') as network:
            with self.assertRaises(APIError):VoiceRecognizer(Config(bot_token='fake'),api).transcribe({'file_id':'file'})
            network.assert_not_called()
