import dataclasses
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from business.bot import BusinessBot, Config, Store, OpenAI, NOTICE, APIError

OWNER=100
CUSTOMER=200
CID='business-connection-test'
NOW=1_800_000_000

class TelegramFake:
    def __init__(self):
        self.calls=[]
        self.connection={'id':CID,'user':{'id':OWNER},'is_enabled':True,'rights':{'can_reply':True}}
    def call(self,method,**params):
        self.calls.append((method,params))
        if method=='getBusinessConnection':return self.connection
        if method=='getWebhookInfo':return {'url':''}
        if method=='getMe':return {'can_connect_to_business':True}
        return {'message_id':999}
    def sent(self):return [p for m,p in self.calls if m=='sendMessage' and 'business_connection_id' in p]

class AIFake:
    def __init__(self):self.calls=[];self.examples=[];self.answer='Привет! Как настроение?';self.hook=None
    def reply(self,text,style,examples=None):
        self.examples=examples or []
        self.calls.append((text,style))
        if self.hook:self.hook()
        return self.answer

class ExecutorFake:
    def __init__(self,defer=False):self.defer=defer;self.pending=[]
    def submit(self,fn,*args):
        if self.defer:self.pending.append((fn,args))
        else:fn(*args)
    def finish(self):
        while self.pending:
            fn,args=self.pending.pop(0);fn(*args)

class BotTests(unittest.TestCase):
    def setUp(self):
        self.config=Config(bot_token='123:'+'x'*30,owner_id=OWNER,openai_key='fake',db_path=':memory:',cooldown_seconds=0)
        self.api=TelegramFake();self.ai=AIFake();self.store=Store(':memory:');self.executor=ExecutorFake()
        self.bot=BusinessBot(self.config,self.api,self.ai,self.store,self.executor,clock=lambda:NOW)
    def tearDown(self):self.store.db.close()
    def event(self,mid=1,text='Привет!',actor=CUSTOMER,**extra):
        m={'business_connection_id':CID,'chat':{'id':CUSTOMER,'type':'private'},'from':{'id':actor},'message_id':mid,'date':NOW,'text':text}
        m.update(extra);return {'update_id':mid,'business_message':m}
    def test_replies_through_business_connection(self):
        self.bot.handle(self.event())
        self.assertEqual(len(self.api.sent()),1)
        sent=self.api.sent()[0]
        self.assertEqual(sent['business_connection_id'],CID)
        self.assertEqual(sent['chat_id'],CUSTOMER)
        self.assertTrue(sent['text'].startswith(NOTICE))
        self.assertFalse(sent['reply_parameters']['allow_sending_without_reply'])
    def test_disclosure_once_without_message_prefix(self):
        self.bot.handle(self.event());self.bot.handle(self.event(2))
        self.assertFalse(self.api.sent()[1]['text'].startswith(NOTICE))
        self.assertNotIn('[ИИ]',self.api.sent()[1]['text'])
    def test_duplicate_update_does_not_generate_again(self):
        self.bot.handle(self.event());self.bot.handle(self.event())
        self.assertEqual(len(self.ai.calls),1);self.assertEqual(len(self.api.sent()),1)
    def test_other_account_cannot_use_service(self):
        self.api.connection['user']['id']=777
        self.bot.handle(self.event());self.assertFalse(self.ai.calls);self.assertFalse(self.api.sent())
    def test_missing_permission_prevents_reply(self):
        self.api.connection['rights']['can_reply']=False
        self.bot.handle(self.event());self.assertFalse(self.ai.calls)
    def test_deprecated_can_reply_does_not_override_rights(self):
        self.api.connection['rights']={};self.api.connection['can_reply']=True
        self.bot.handle(self.event());self.assertFalse(self.ai.calls)
    def test_disabled_connection_prevents_reply(self):
        self.api.connection['is_enabled']=False
        self.bot.handle(self.event());self.assertFalse(self.ai.calls)
    def test_owner_manual_reply_pauses_chat(self):
        self.bot.handle(self.event(actor=OWNER));self.bot.handle(self.event(2))
        self.assertFalse(self.ai.calls)
    def test_bot_output_does_not_start_loop_or_pause(self):
        self.bot.handle(self.event(actor=OWNER,sender_business_bot={'id':99}));self.bot.handle(self.event(2))
        self.assertEqual(len(self.api.sent()),1)
    def test_customer_stop_persists_after_owner_reply(self):
        self.bot.handle(self.event(text='/stop'));self.bot.handle(self.event(2,actor=OWNER));self.bot.handle(self.event(3))
        self.assertFalse(self.ai.calls)
        self.store.resume_chat(CUSTOMER);self.bot.handle(self.event(4));self.assertEqual(len(self.api.sent()),1)
    def test_old_backlog_not_answered(self):
        self.bot.handle(self.event(date=NOW-60));self.assertFalse(self.ai.calls)
    def test_sensitive_message_never_sent_to_provider(self):
        self.bot.handle(self.event(text='Мой пароль 123456'))
        self.assertFalse(self.ai.calls);self.assertFalse(self.api.sent())
    def test_model_review_is_not_sent(self):
        self.ai.answer=None;self.bot.handle(self.event());self.assertFalse(self.api.sent())
    def test_sensitive_model_output_is_not_sent(self):
        self.ai.answer='Гарантирую оплату';self.bot.handle(self.event());self.assertFalse(self.api.sent())
    def test_revocation_during_ai_cancels_reply(self):
        self.ai.hook=lambda:self.api.connection.update(is_enabled=False)
        self.bot.handle(self.event());self.assertFalse(self.api.sent())
    def test_manual_intervention_cancels_pending_reply(self):
        self.executor.defer=True;self.bot.handle(self.event());self.bot.handle(self.event(2,actor=OWNER));self.executor.finish()
        self.assertFalse(self.ai.calls);self.assertFalse(self.api.sent())
    def test_deletion_during_ai_cancels_reply(self):
        self.ai.hook=lambda:self.bot.handle({'deleted_business_messages':{'business_connection_id':CID,'chat':{'id':CUSTOMER},'message_ids':[1]}})
        self.bot.handle(self.event());self.assertFalse(self.api.sent())
    def test_newer_message_replaces_pending_older(self):
        self.executor.defer=True;self.bot.handle(self.event());self.bot.handle(self.event(2,'Как дела?'));self.executor.finish()
        self.assertEqual([x[0] for x in self.ai.calls],['Как дела?']);self.assertEqual(len(self.api.sent()),1)
    def test_new_media_cancels_pending_text(self):
        self.executor.defer=True;self.bot.handle(self.event());e=self.event(2);del e['business_message']['text'];e['business_message']['voice']={'file_id':'voice'};self.bot.handle(e);self.executor.finish()
        self.assertFalse(self.api.sent())
    def test_global_pause_is_owner_only(self):
        self.bot.handle({'message':{'chat':{'id':CUSTOMER,'type':'private'},'from':{'id':CUSTOMER},'text':'/pause'}})
        self.assertFalse(self.store.paused())
        self.bot.handle({'message':{'chat':{'id':OWNER,'type':'private'},'from':{'id':OWNER},'text':'/pause'}})
        self.bot.handle(self.event());self.assertTrue(self.store.paused());self.assertFalse(self.ai.calls)
    def test_setup_mode_never_replies_as_business_account(self):
        self.bot.config=dataclasses.replace(self.config,owner_id=0)
        self.bot.handle(self.event());self.assertFalse(self.api.calls)
        self.bot.handle({'message':{'chat':{'id':OWNER,'type':'private'},'from':{'id':OWNER},'text':'/id'}})
        self.assertEqual(self.api.calls[0][1]['chat_id'],OWNER)
    def test_shutdown_invalidates_pending_without_persistently_pausing(self):
        self.executor.defer=True;self.bot.handle(self.event());self.bot.running=False;self.store.invalidate();self.executor.finish()
        self.assertFalse(self.api.sent());self.assertFalse(self.store.paused())
    def test_foreign_chat_never_leaves_customer_metadata(self):
        self.api.connection['user']['id']=999
        self.bot.handle(self.event(text='/stop'))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM chats').fetchone()[0],0)
    def test_persisted_deduplication_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path=folder+'/state.sqlite3';s=Store(path);s.connection(self.api.connection,OWNER);s.begin(CID,CUSTOMER,1,NOW);s.db.close()
            again=Store(path);self.assertIsNone(again.begin(CID,CUSTOMER,1,NOW));again.db.close()
    def test_hourly_limit(self):
        self.bot.config=dataclasses.replace(self.config,max_replies_per_hour=1)
        self.bot.handle(self.event());self.bot.handle(self.event(2));self.assertEqual(len(self.api.sent()),1)
    def test_cooldown(self):
        self.bot.config=dataclasses.replace(self.config,cooldown_seconds=5)
        self.bot.handle(self.event());self.bot.handle(self.event(2));self.assertEqual(len(self.api.sent()),1)
    def test_network_error_is_not_retried(self):
        original=self.api.call
        def call(method,**params):
            if method=='sendMessage':raise APIError(502)
            return original(method,**params)
        self.api.call=call
        self.bot.handle(self.event());self.bot.handle(self.event());self.assertEqual(len(self.ai.calls),1)

class PersonalizationTests(unittest.TestCase):
    setUp=BotTests.setUp
    tearDown=BotTests.tearDown
    event=BotTests.event
    def command(self,text,actor=OWNER):
        self.bot.handle({'message':{'chat':{'id':actor,'type':'private'},'from':{'id':actor},'text':text}})
    def test_example_is_used_for_next_reply(self):
        self.command('/example как дела? => да норм, ты как')
        self.bot.handle(self.event())
        self.assertEqual(self.ai.examples,[{'incoming':'как дела?','owner_reply':'да норм, ты как'}])
    def test_customer_cannot_change_personality(self):
        self.command('/example привет => чужой ответ',CUSTOMER)
        self.command('/style формальный',CUSTOMER)
        self.assertEqual(self.store.examples(),[])
        self.assertEqual(self.store.get('style','default'),'default')
    def test_examples_are_bounded(self):
        for i in range(10):self.command(f'/example вопрос {chr(65+i)} => ответ {chr(65+i)}')
        values=self.store.examples();self.assertEqual(len(values),8)
        self.assertEqual(values[0]['incoming'],'вопрос C')
    def test_duplicate_example_not_repeated(self):
        self.command('/example привет => здарова');self.command('/example привет => здарова')
        self.assertEqual(len(self.store.examples()),1)
    def test_sensitive_example_is_rejected(self):
        self.command('/example какой пароль? => секрет 123456')
        self.assertEqual(self.store.examples(),[])
    def test_invalid_example_is_rejected(self):
        for text in ['/example привет','/example => ответ','/example привет =>','/example '+('x'*501)+' => ответ']:self.command(text)
        self.assertEqual(self.store.examples(),[])
    def test_clear_style_keeps_manual_pause(self):
        self.command('/example привет => здарова');self.command('/pause');self.command('/clearstyle')
        self.assertEqual(self.store.examples(),[]);self.assertTrue(self.store.paused())
    def test_style_change_cancels_inflight_reply(self):
        self.executor.defer=True;self.bot.handle(self.event());self.command('/example привет => здарова');self.executor.finish()
        self.assertFalse(self.api.sent())
    def test_style_samples_not_added_to_actual_business_reply(self):
        self.command('/example как дела? => да норм, ты как');self.bot.handle(self.event())
        self.assertNotIn('owner_reply',self.api.sent()[0]['text'])

class ProviderTests(unittest.TestCase):
    def test_valid_json_reply(self):
        config=Config(bot_token='fake',openai_key='fake');provider=OpenAI(config)
        response={'choices':[{'message':{'content':json.dumps({'action':'reply','reply':'Привет!'})}}]}
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
            self.assertEqual(provider.reply('Привет','Кратко'),'Привет!')
    def test_style_and_examples_are_quoted_in_provider_request(self):
        provider=OpenAI(Config(bot_token='fake',openai_key='fake'))
        samples=[{'incoming':'привет','owner_reply':'здарова'}]
        response={'choices':[{'message':{'content':json.dumps({'action':'reply','reply':'приветик'})}}]}
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as network:
            provider.reply('Как ты?','Коротко, на ты',samples)
            body=json.loads(network.call_args.args[0].data)
            data=json.loads(body['messages'][1]['content'])
            self.assertEqual(data['style_examples'],samples)
            self.assertEqual(data['owner_style'],'Коротко, на ты')
            self.assertEqual(len(body['messages']),2)
    def test_secrets_blocked_before_network(self):
        with patch('urllib.request.urlopen') as network:
            self.assertIsNone(OpenAI(Config(bot_token='fake')).reply('Мой пароль 123456',''))
            network.assert_not_called()
    def test_review_and_malformed_json(self):
        provider=OpenAI(Config(bot_token='fake'))
        for content in ['{"action":"review","reply":"no"}','{"action":"reply","reply":42}']:
            response={'choices':[{'message':{'content':content}}]}
            with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
                self.assertIsNone(provider.reply('Привет',''))
    def test_configuration_never_uses_personal_api_id(self):
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123:'+'a'*30,'TELEGRAM_OWNER_ID':'0'},clear=True):
            config=Config.env();self.assertEqual(config.owner_id,0)
