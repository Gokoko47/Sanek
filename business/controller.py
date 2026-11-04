"""Business message orchestration: context, quiet windows and owner approvals."""
from __future__ import annotations
import concurrent.futures
import dataclasses
import logging
import math
import re
import threading
import time
from .core import Config, Store, Telegram, OpenAI, APIError, NOTICE, MAX_EXAMPLES, EXAMPLE_LIMIT
from .bot_types import MAX_BATCH_MESSAGES, MAX_BATCH_CHARS, is_sensitive
from .history import History
from .scheduler import QuietScheduler
from .voice import VoiceRecognizer
from .drafts import Drafts
from .menu import Menu

LOG=logging.getLogger('pakostnik.business')


@dataclasses.dataclass
class Pending:
    mid: int
    date: int
    text: str = ''
    media: dict | None = None


@dataclasses.dataclass
class Batch:
    generation: int
    opened: float
    items: list[Pending]


class BusinessBot:
    def __init__(self,config: Config,telegram=None,ai=None,store=None,executor=None,clock=time.time,
                 scheduler=None,monotonic=time.monotonic,voice=None):
        self.config=config
        self.telegram=telegram or Telegram(config.bot_token)
        self.ai=ai or OpenAI(config)
        self.store=store or Store(config.db_path)
        self.own_store=store is None
        self.pool=executor or concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.slots=threading.BoundedSemaphore(8)
        self.clock,self.monotonic=clock,monotonic
        self.scheduler=scheduler
        self.voice=voice or VoiceRecognizer(config,self.telegram)
        self.history=History(self.store,ttl=config.context_ttl_seconds,max_messages=config.context_max_messages,max_chars=config.context_max_chars)
        self.drafts=Drafts(self.store,ttl=config.max_message_age_seconds)
        self.ui=Menu(self)
        self.started=int(clock())
        self.running=True
        self.closed=False
        self.stop_event=threading.Event()
        self.batch_lock=threading.RLock()
        self.batches={}
        self.history.prune(clock())

    def delay(self):
        try:
            value=float(self.store.get('debounce_seconds',str(self.config.debounce_seconds)))
            return value if math.isfinite(value) and 0<=value<=30 else self.config.debounce_seconds
        except (ValueError,TypeError):
            return self.config.debounce_seconds

    def set_delay(self,value):
        if not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=30:
            raise ValueError('Delay must be between 0 and 30 seconds')
        # Already queued windows keep their deadline; the next incoming starts/extends with the new setting.
        self.store.set('debounce_seconds',str(value))

    def voice_enabled(self):
        return self.store.get('voice_enabled','1' if self.config.voice_enabled else '0')=='1'

    def refresh(self,cid):
        data=self.telegram.call('getBusinessConnection',business_connection_id=cid)
        allowed=isinstance(data,dict) and data.get('id')==cid and self.store.connection(data,self.config.owner_id)
        if not allowed:
            self.cancel_connection(cid)
            self.history.clear(cid)
            self.drafts.clear(cid)
        return allowed

    def current(self,cid,chat,mid,generation,date):
        return self.running and self.clock()-date<=self.config.max_message_age_seconds and self.store.valid(cid,chat,mid,generation,self.clock())

    def cancel(self,cid,chat):
        key=(cid,chat)
        with self.batch_lock:
            self.batches.pop(key,None)
            if self.scheduler:self.scheduler.cancel(key)

    def cancel_all(self):
        with self.batch_lock:
            self.batches.clear()
            if self.scheduler:self.scheduler.cancel_all()

    def cancel_connection(self,cid):
        with self.batch_lock:
            for key in list(self.batches):
                if key[0]==cid:
                    self.batches.pop(key,None)
                    if self.scheduler:self.scheduler.cancel(key)

    def set_paused(self,value):
        self.store.pause(value)
        self.cancel_all()

    def set_style(self,text):
        if not 0<len(text)<=500 or is_sensitive(text):
            raise ValueError('Invalid style')
        with self.store.lock:
            self.store.set('style',text)
            self.store.invalidate()
        self.cancel_all()

    def reset_style(self):
        with self.store.lock:
            self.store.set('examples','[]')
            self.store.set('style',self.config.style)
            self.store.invalidate()
        self.cancel_all()

    def clear_context(self,cid=None,chat=None):
        if cid is None:
            self.store.invalidate();self.cancel_all()
        else:
            self.store.cancel_chat(cid,chat);self.cancel(cid,chat)
        self.history.clear(cid,chat)
        self.drafts.clear(cid,chat)

    def show_examples(self):
        values=self.store.examples()
        text='Образцов пока нет. Добавь: /example входящее => мой ответ'
        if values:text='\n\n'.join(f"{i+1}. На: {e['incoming'][:100]}\nЯ: {e['owner_reply'][:100]}" for i,e in enumerate(values))
        return self.ui.send(text,[[self.ui.button('К профилю','style')]])

    def _review(self,cid,chat,reason):
        self.cancel(cid,chat)
        self.history.clear(cid,chat)
        self.drafts.clear(cid,chat)
        first=self.store.flag_review(cid,chat,reason)
        if first:
            c=self.store.chat(cid,chat)
            try:
                self.ui.send(f"Нужен ручной ответ: {c['title'] or chat}.\n{reason}\nАвтоответы в этом чате приостановлены до твоего ответа или явного возобновления.",
                             [[self.ui.button('Управление чатом','chat',cid=cid,chat=chat)]])
            except APIError:
                LOG.warning('Owner notification unavailable; the chat remains held for review')

    def _budget_notice(self):
        try:
            previous=float(self.store.get('budget_notice','0'))
        except ValueError:previous=0
        if self.clock()-previous>=600:
            self.store.set('budget_notice',str(self.clock()))
            try:self.ui.main('Достигнут лимит API/автоответов. Ожидающие сообщения не будут отправлены позже автоматически; ответь вручную.')
            except APIError:LOG.warning('Owner budget notification unavailable')

    def _reserve_ai(self):
        if self.store.reserve_ai(self.clock(),self.config):return True
        self._budget_notice();return False

    def owner_message(self,message):
        sender=message.get('from') or {};chat=message.get('chat') or {}
        actor=sender.get('id');text=message.get('text','').strip()
        if chat.get('type')!='private' or actor!=chat.get('id'):return
        if text in ('/start','/id'):
            self.telegram.call('sendMessage',chat_id=chat['id'],text=f'Ваш Telegram user ID: {actor}\nЭто бот Telegram Business. Токены сюда присылать не нужно.')
            if actor==self.config.owner_id and actor:self.ui.main()
            return
        if not actor or actor!=self.config.owner_id:return
        if not text.startswith('/') and self.ui.owner_input(message):return
        command,_,value=text.partition(' ');value=value.strip()
        if command in ('/menu','/help'):return self.ui.main()
        if command=='/status':return self.ui.status()
        if command=='/chats':return self.ui.chats()
        if command=='/pause':self.set_paused(True);return self.ui.main('Автоответы остановлены.')
        if command=='/resume':self.set_paused(False);return self.ui.main('Автоответы возобновлены. Паузы отдельных чатов сохраняются.')
        if command=='/resumechat' and re.fullmatch(r'[1-9]\d*',value):
            self.store.resume_chat(int(value))
            for c in self.store.list_chats(self.config.owner_id):
                if c['chat']==int(value):self.cancel(c['connection'],c['chat'])
            return self.ui.main('Локальная пауза выбранного чата снята.')
        if command=='/style':
            if not value:return self.ui.style()
            if len(value)>500 or is_sensitive(value):return self.ui.main('До 500 символов, без секретов, для описания манеры общения.')
            self.set_style(value);return self.ui.style()
        if command=='/example':
            incoming,separator,own=value.partition('=>');incoming,own=incoming.strip(),own.strip()
            if not separator or not 0<len(incoming)<=EXAMPLE_LIMIT or not 0<len(own)<=EXAMPLE_LIMIT:
                return self.ui.send('/example входящее сообщение => мой обычный ответ\nДо 500 символов в каждой части.')
            if is_sensitive(incoming) or is_sensitive(own):return self.ui.send('Добавь бытовой пример без секретов и важных обязательств.')
            self.store.add_example(incoming,own);self.cancel_all();return self.ui.send(f'Образец сохранён. Всего: {len(self.store.examples())}/{MAX_EXAMPLES}.')
        if command=='/examples':return self.show_examples()
        if command=='/clearstyle':self.reset_style();return self.ui.style()
        if command=='/clearcontext':self.clear_context();return self.ui.main('Весь короткий контекст очищен. Образцы стиля сохранены.')
        if command=='/delay':
            if not value:return self.ui.delay()
            try:self.set_delay(float(value))
            except (ValueError,TypeError):return self.ui.send('Задержка: число от 0 до 30 секунд.')
            return self.ui.delay()
        if command=='/voice':return self.ui.voice()
        if command=='/memory':return self.ui.memory()

    def _change_or_delete(self,update):
        m=update.get('deleted_business_messages') or update.get('edited_business_message')
        if not m:return
        cid=m.get('business_connection_id');chat=(m.get('chat') or {}).get('id')
        if self.store.owner(cid)!=self.config.owner_id or not chat:return
        ids=m.get('message_ids',[m.get('message_id')])
        self.store.edited_or_deleted(cid,chat,ids)
        self.cancel(cid,chat)
        # Drop the whole short context to avoid retaining a paraphrase in an older bot reply.
        self.history.clear(cid,chat)
        self.drafts.clear(cid,chat)
        if 'edited_business_message' in update and not m.get('sender_business_bot') and (m.get('from') or {}).get('id')==self.config.owner_id:
            self.store.stop_chat(cid,chat,until=self.clock()+self.config.manual_pause_seconds)

    def handle(self,update):
        if not self.running:return
        if 'message' in update:self.owner_message(update['message'])
        if 'callback_query' in update:self.ui.callback(update['callback_query'])
        if not self.config.owner_id:return
        if 'business_connection' in update:
            data=update['business_connection'];allowed=self.store.connection(data,self.config.owner_id)
            if not allowed:
                self.cancel_connection(data['id']);self.history.clear(data['id']);self.drafts.clear(data['id'])
        self._change_or_delete(update)
        m=update.get('business_message')
        if not isinstance(m,dict):return
        cid=m.get('business_connection_id');chat=m.get('chat') or {};peer=chat.get('id');sender=m.get('from') or {}
        if not isinstance(cid,str) or not isinstance(peer,int) or peer<=0 or peer==self.config.owner_id or chat.get('type')!='private':return
        if self.store.owner(cid) is None:self.refresh(cid)
        if self.store.owner(cid)!=self.config.owner_id:return
        if m.get('sender_business_bot'):return
        if not isinstance(sender.get('id'),int):return
        text=m.get('text','').strip()
        if sender['id']!=self.config.owner_id and text.lower()=='/stop':
            self.store.stop_chat(cid,peer,stopped=True);self.cancel(cid,peer);self.history.clear(cid,peer);self.drafts.clear(cid,peer);return
        date=m.get('date',0);mid=m.get('message_id',0)
        if not isinstance(date,int) or not isinstance(mid,int) or mid<=0 or sender.get('is_bot') or date<self.started or self.clock()-date>self.config.max_message_age_seconds or date>self.clock()+30:return
        title=' '.join(filter(None,[chat.get('first_name',''),chat.get('last_name','')])).strip() or chat.get('username','') or str(peer)
        self.store.touch(cid,peer,title,self.clock())
        row=self.store.chat(cid,peer)
        if sender['id']==self.config.owner_id:
            self.store.stop_chat(cid,peer,until=self.clock()+self.config.manual_pause_seconds);self.cancel(cid,peer);self.drafts.clear(cid,peer)
            if not row['stopped'] and row['mode']!='off' and not self.store.paused():
                self.history.remember(cid,peer,m.get('message_id',0),'assistant',m.get('text',''),self.clock())
            return
        if not self.store.connected(cid) or self.store.paused() or row['stopped'] or row['mode']=='off' or row['needs_review']:return
        media=None
        for kind in ('voice','video_note'):
            if isinstance(m.get(kind),dict):media={**m[kind],'kind':kind};break
        if not text and not media:
            self._review(cid,peer,'Это вложение пока требует ручного просмотра.');return
        if len(text)>MAX_BATCH_CHARS:
            self._review(cid,peer,'Сообщение слишком длинное для автоматического ответа.');return
        if text and is_sensitive(text):
            self._review(cid,peer,'Важный или чувствительный вопрос.');return
        if media and (not self.voice_enabled() or not media.get('file_id') or media.get('duration',0)>self.config.voice_max_seconds or media.get('file_size',0)>self.config.voice_max_bytes):
            self._review(cid,peer,'Распознавание выключено или запись превышает лимит.');return
        # During a manual pause, text is context only and never triggers AI.
        if text:self.history.remember(cid,peer,mid,'user',text,self.clock())
        generation=self.store.begin(cid,peer,mid,self.clock())
        if generation is None:return
        self.collect(cid,peer,generation,Pending(mid,date,text,media))

    def collect(self,cid,chat,generation,item):
        key=(cid,chat);overflow=False;immediate=False
        with self.batch_lock:
            old=self.batches.get(key)
            items=(old.items if old else [])+[item]
            if len(items)>MAX_BATCH_MESSAGES or sum(len(m.text) for m in items)>MAX_BATCH_CHARS or sum(m.media is not None for m in items)>3:
                self.batches.pop(key,None);overflow=True
                if self.scheduler:self.scheduler.cancel(key)
            else:
                batch=Batch(generation,old.opened if old else self.monotonic(),items);self.batches[key]=batch
                quiet=self.delay()
                if quiet==0:immediate=True
                else:
                    if self.scheduler is None:self.scheduler=QuietScheduler(self.monotonic)
                    cap=max(quiet,self.config.max_batch_wait_seconds)
                    remaining=max(0,cap-(self.monotonic()-batch.opened))
                    self.scheduler.schedule(key,min(quiet,remaining),lambda:self.flush(key,generation))
        if overflow:self._review(cid,chat,'Серия сообщений слишком большая; нужен общий ручной ответ.')
        elif immediate:self.flush(key,generation)

    def flush(self,key,generation):
        with self.batch_lock:
            batch=self.batches.get(key)
            if not batch or batch.generation!=generation:return
            self.batches.pop(key,None)
        cid,chat=key;last=batch.items[-1]
        if not self.current(cid,chat,last.mid,generation,min(m.date for m in batch.items)):return
        if not self.slots.acquire(blocking=False):
            self._review(cid,chat,'Очередь ИИ заполнена.');return
        try:self.pool.submit(self.generate,cid,chat,generation,batch.items)
        except RuntimeError:
            self.slots.release();self._review(cid,chat,'Сервис останавливается; ответь вручную.')

    def generate(self,cid,chat,generation,items):
        mids=[m.mid for m in items];mid=mids[-1];date=min(m.date for m in items)
        try:
            if not self.current(cid,chat,mid,generation,date):return
            if not self.store.budget_available(self.clock(),self.config):self._budget_notice();return
            parts=[]
            for item in items:
                if not self.current(cid,chat,mid,generation,date):return
                text=item.text
                if item.media:
                    if not self.voice_enabled():return
                    if not self._reserve_ai():return
                    transcript=self.voice.transcribe(item.media)
                    if not self.current(cid,chat,mid,generation,date):return
                    text=(text+'\n' if text else '')+transcript
                    if is_sensitive(text):self._review(cid,chat,'В записи распознан важный или чувствительный вопрос.');return
                    self.history.remember(cid,chat,item.mid,'user',text,self.clock())
                parts.append(text)
            text='\n'.join(parts)
            if not text.strip() or len(text)>MAX_BATCH_CHARS or is_sensitive(text):
                self._review(cid,chat,'Серия требует ручного ответа.');return
            context=self.history.snapshot(cid,chat,set(mids),self.clock())
            if is_sensitive(' '.join(e['text'] for e in context)):
                self._review(cid,chat,'Контекст требует ручной проверки.');return
            if not self._reserve_ai():return
            row=self.store.chat(cid,chat)
            reply=self.ai.reply(text,row['style'] or self.store.get('style',self.config.style),self.store.examples(),context)
            if not self.current(cid,chat,mid,generation,date):return
            if not isinstance(reply,str) or not 0<len(reply.strip())<=1500 or is_sensitive(reply):
                self._review(cid,chat,'ИИ передал вопрос для ручного решения.');return
            if row['mode']=='assist':
                token=self.drafts.create(cid,chat,generation,date,mids,text,reply.strip(),self.clock());self.ui.draft(token);return
            if not self.refresh(cid):return
            self.send_reply(cid,chat,mid,generation,date,reply.strip())
        except APIError as error:
            LOG.warning('Reply not confirmed, API status %s; no automatic resend',error.code)
            self._review(cid,chat,'Ошибка сервиса; проверь переписку и ответь вручную.')
        except Exception:
            LOG.error('Reply failed; no automatic resend')
            self._review(cid,chat,'Не удалось подготовить ответ; нужна ручная проверка.')
        finally:self.slots.release()

    def send_reply(self,cid,chat,mid,generation,date,reply):
        disclose=self.store.reserve(cid,chat,mid,generation,self.clock(),self.config)
        if disclose is None or not self.current(cid,chat,mid,generation,date):return False
        result=self.telegram.call('sendMessage',business_connection_id=cid,chat_id=chat,
            text=(NOTICE+'\n\n' if disclose else '')+reply,
            reply_parameters={'message_id':mid,'allow_sending_without_reply':False})
        if disclose:self.store.disclosed(cid,chat)
        if self.current(cid,chat,mid,generation,date) and isinstance(result,dict) and isinstance(result.get('message_id'),int):
            self.history.remember(cid,chat,result['message_id'],'assistant',reply,self.clock())
        return True

    def approve(self,token,revision,teach=False):
        d=self.drafts.get(token,self.clock())
        if not d or d['revision']!=revision or d['state']!='pending' or not self.current(d['connection'],d['chat'],d['mid'],d['generation'],d['source_date']):
            return self.ui.main('Предложение уже обработано, изменилось или устарело. Собеседнику ничего не отправлено этим нажатием.')
        if teach and (not d['edited'] or len(d['source'])>500 or len(d['body'])>500):return self.ui.main('Как образец можно сохранить только свой исправленный вариант до 500 символов.')
        if is_sensitive(d['body']):return self.ui.main('Чувствительный ответ отправь вручную в Telegram.')
        try:
            if not self.refresh(d['connection']):return self.ui.main('Telegram больше не разрешает ответ.')
            claimed=self.drafts.claim(token,revision,self.clock())
            if not claimed:return self.ui.main('Предложение уже обработано.')
            ok=self.send_reply(d['connection'],d['chat'],d['mid'],d['generation'],d['source_date'],d['body'])
            self.drafts.finish(token,'sent' if ok else 'failed')
            if ok and teach:
                self.store.add_example(d['source'],d['body']);self.cancel_all()
            return self.ui.main('Ответ отправлен.' if ok else 'Ответ не отправлен: контекст изменился или достигнут лимит. Проверь переписку.')
        except APIError as error:
            self.drafts.finish(token,'failed')
            LOG.warning('Draft delivery unconfirmed, status %s',error.code)
            return self.ui.main('Доставка не подтверждена. Повтор автоматически не выполняется; проверь переписку перед ручной отправкой.')

    def request_stop(self):
        self.running=False;self.stop_event.set();self.store.invalidate();self.cancel_all()

    def close(self):
        if self.closed:return
        self.closed=True;self.request_stop()
        if self.scheduler:self.scheduler.close()
        if hasattr(self.pool,'shutdown'):self.pool.shutdown(wait=True,cancel_futures=True)
        if self.own_store:self.store.db.close()

    def startup_call(self,method):
        backoff=2
        while self.running:
            try:return self.telegram.call(method)
            except APIError as error:
                if error.code in (401,409):raise RuntimeError('Invalid bot token or a second polling instance') from None
                LOG.warning('Startup network unavailable, status %s; waiting',error.code)
                if self.stop_event.wait(min(60,max(backoff,error.retry_after))):return None
                backoff=min(30,backoff*2)
        return None

    def run(self):
        try:
            webhook=self.startup_call('getWebhookInfo')
            if webhook is None:return
            if webhook.get('url'):raise RuntimeError('A webhook is configured. Disable the former integration before polling.')
            me=self.startup_call('getMe')
            if me is None:return
            if self.config.owner_id and not me.get('can_connect_to_business'):raise RuntimeError('Enable Business Mode in BotFather')
            if self.config.owner_id:
                try:self.telegram.call('setMyCommands',scope={'type':'chat','chat_id':self.config.owner_id},commands=[
                    {'command':'menu','description':'Управление'}, {'command':'pause','description':'Остановить ИИ'},
                    {'command':'resume','description':'Включить ИИ'}, {'command':'status','description':'Состояние'},
                    {'command':'id','description':'Мой ID'}])
                except APIError:LOG.warning('Command registration unavailable; /menu remains usable')
            LOG.info('Business service running; %s','setup only' if not self.config.owner_id else 'configured owner')
            backoff=2
            while self.running:
                try:
                    from .core import ALLOWED_UPDATES
                    updates=self.telegram.call('getUpdates',offset=int(self.store.get('offset','0')),timeout=30,allowed_updates=ALLOWED_UPDATES)
                    if not isinstance(updates,list):raise APIError(502)
                    for update in updates:
                        if not self.running:break
                        try:self.handle(update)
                        except APIError as error:LOG.warning('Update needs attention, API status %s',error.code)
                        except Exception:LOG.error('Update could not be processed')
                        self.store.set('offset',str(update['update_id']+1))
                    self.history.prune(self.clock());self.drafts.prune(self.clock());backoff=2
                except APIError as error:
                    if error.code in (401,409):raise RuntimeError('Invalid bot token or a second polling instance') from None
                    LOG.warning('Telegram temporarily unavailable, status %s',error.code)
                    self.stop_event.wait(min(60,max(backoff,error.retry_after)));backoff=min(30,backoff*2)
        finally:self.close()
