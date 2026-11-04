"""Recovery and concurrent delivery checks without real accounts or API requests."""
import concurrent.futures
import io
import json
import threading
import unittest
from unittest.mock import patch
from business.bot import APIError, BusinessBot, Config, OpenAI, Store, Telegram
from business.drafts import Drafts


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:')
        self.config=Config(bot_token='123:'+'x'*30,owner_id=100,openai_key='test',db_path=':memory:')
        self.calls=[]
        self.api=type('API',(),{})()
        self.api.call=self.call
        self.bot=BusinessBot(self.config,telegram=self.api,store=self.store)
    def tearDown(self):
        self.bot.close();self.store.db.close()
    def call(self,method,**params):
        self.calls.append((method,params))
        if method=='getWebhookInfo':return {'url':''}
        if method=='getMe':return {'can_connect_to_business':True}
        if method=='getUpdates':self.bot.request_stop();return []
        return True
    def test_startup_recovers_without_restarting_process(self):
        values=iter([APIError(502),APIError(429,7),{'url':''}])
        def call(*args,**kwargs):
            result=next(values)
            if isinstance(result,Exception):raise result
            return result
        self.api.call=call
        with patch.object(self.bot.stop_event,'wait',return_value=False) as wait:
            self.assertEqual(self.bot.startup_call('getWebhookInfo'),{'url':''})
        self.assertEqual([c.args[0] for c in wait.call_args_list],[2,7])
    def test_shutdown_interrupts_startup_recovery(self):
        self.api.call=lambda *a,**k:(_ for _ in ()).throw(APIError(502))
        with patch.object(self.bot.stop_event,'wait',return_value=True):
            self.assertIsNone(self.bot.startup_call('getMe'))
    def test_fatal_token_and_conflict_do_not_retry(self):
        for code in (401,409):
            with self.subTest(code=code),patch.object(self.api,'call',side_effect=APIError(code)),patch.object(self.bot.stop_event,'wait') as wait:
                with self.assertRaises(RuntimeError):self.bot.startup_call('getMe')
                wait.assert_not_called()
    def test_polling_includes_callbacks_and_registers_private_commands(self):
        self.bot.run()
        registered=next(p for m,p in self.calls if m=='setMyCommands')
        self.assertEqual(registered['scope'],{'type':'chat','chat_id':100})
        poll=next(p for m,p in self.calls if m=='getUpdates')
        self.assertIn('callback_query',poll['allowed_updates'])
        self.assertIn('deleted_business_messages',poll['allowed_updates'])
        self.assertTrue(self.bot.closed)
    def test_existing_webhook_is_preserved(self):
        self.api.call=lambda method,**params:{'url':'https://example.invalid/hook'}
        with self.assertRaisesRegex(RuntimeError,'webhook'):self.bot.run()
        self.assertTrue(self.bot.closed)
    def test_polling_recovers_and_keeps_offset(self):
        self.store.set('offset','42');attempts=0
        original=self.call
        def call(method,**params):
            nonlocal attempts
            if method=='getUpdates':
                attempts+=1
                if attempts==1:raise APIError(502)
                self.assertEqual(params['offset'],42)
            return original(method,**params)
        self.api.call=call
        with patch.object(self.bot.stop_event,'wait',return_value=False) as wait:self.bot.run()
        self.assertEqual(attempts,2);wait.assert_called_once_with(2)
    def test_concurrent_draft_claim_allows_one_attempt(self):
        drafts=Drafts(self.store)
        token=drafts.create('c',200,1,100,[10],'привет','здарова',100)
        barrier=threading.Barrier(8)
        def claim(_):barrier.wait(timeout=2);return drafts.claim(token,0,100)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(claim,range(8)))
        self.assertEqual(sum(result is not None for result in results),1)
    def test_more_than_fifteen_chats_are_accessible(self):
        self.store.connection({'id':'c','user':{'id':100},'is_enabled':True,'rights':{'can_reply':True}},100)
        for peer in range(200,234):self.store.touch('c',peer,str(peer),peer)
        pages=[self.store.list_chats(100,offset=n*15) for n in range(3)]
        self.assertEqual([len(p) for p in pages],[15,15,4])
        self.assertEqual(len({p['chat'] for page in pages for p in page}),34)


class TransportTests(unittest.TestCase):
    def test_malformed_telegram_response_is_redacted(self):
        for data in ([],None,'unexpected'):
            with self.subTest(data=data),patch('urllib.request.urlopen') as urlopen:
                urlopen.return_value.__enter__.return_value.read.return_value=json.dumps(data).encode()
                with self.assertRaises(APIError) as error:Telegram('secret').call('getMe')
                self.assertNotIn('secret',str(error.exception))
    def test_unsafe_file_paths_and_metadata_never_download(self):
        api=Telegram('secret')
        for metadata in (None,[],{'file_path':'../private'},{'file_path':'https://other.invalid/file'},
                         {'file_path':'/voice/a.ogg'},{'file_path':'voice/a.ogg','file_size':None}):
            with self.subTest(metadata=metadata),patch.object(api,'call',return_value=metadata),patch('urllib.request.urlopen') as download:
                with self.assertRaises(APIError):api.download('file',1024)
                download.assert_not_called()
    def test_download_is_bounded_and_uses_official_file_endpoint(self):
        api=Telegram('secret')
        with patch.object(api,'call',return_value={'file_path':'voice/a.ogg','file_size':5}),patch('urllib.request.urlopen') as download:
            response=download.return_value.__enter__.return_value
            response.read.return_value=b'voice'
            self.assertEqual(api.download('file',10),b'voice')
            response.read.assert_called_once_with(11)
            self.assertEqual(download.call_args.args[0],'https://api.telegram.org/file/botsecret/voice/a.ogg')
    def test_invalid_context_never_reaches_provider(self):
        ai=OpenAI(Config(bot_token='test'))
        for text,context in ((None,[]),('привет',[{'text':None}]),('привет',[None]),('привет','invalid')):
            with self.subTest(text=text,context=context),patch('urllib.request.urlopen') as provider:
                self.assertIsNone(ai.reply(text,'коротко',context=context));provider.assert_not_called()
