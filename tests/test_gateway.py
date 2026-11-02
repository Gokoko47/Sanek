import importlib.util
import io
import json
import os
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from pathlib import Path
from http.server import ThreadingHTTPServer
spec=importlib.util.spec_from_file_location('gateway',Path(__file__).resolve().parents[1]/'server/server.py')
gateway=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)

class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),gateway.Gateway)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def setUp(self):
        gateway.Gateway.calls=0
        self.env=patch.dict(os.environ,{'PAKOSTNIK_TOKEN':'t'*32,'OPENAI_API_KEY':'test-key'})
        self.env.start()
    def tearDown(self):
        self.env.stop()
    def request(self,payload,token='t'*32,path='/reply',content_type='application/json'):
        data=payload if isinstance(payload,bytes) else json.dumps(payload).encode()
        # Use a direct local opener for the test server only.
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request=urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}'+path,data=data,headers={'Authorization':'Bearer '+token,'Content-Type':content_type})
        try:
            with opener.open(request,timeout=5) as response:
                return response.status,json.load(response)
        except urllib.error.HTTPError as e:
            return e.code,json.load(e)
    def provider(self,result):
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(result)}}]}).encode())
    def test_reject_wrong_token_before_provider(self):
        with patch.object(gateway.urllib.request,'urlopen') as provider:
            self.assertEqual(self.request({'text':'hello'},'wrong')[0],401)
            provider.assert_not_called()
    def test_only_reply_route(self):
        self.assertEqual(self.request({'text':'hi'},path='/wrong')[0],404)
    def test_invalid_text(self):
        for data in [{'text':42},{'text':''},{'text':'x'*4001},{}, {'text':'hi','style':42}]:
            self.assertEqual(self.request(data)[0],400)
    def test_harmless_reply(self):
        with patch.object(gateway.urllib.request,'urlopen',return_value=self.provider({'action':'reply','reply':'Привет!'})) as provider:
            self.assertEqual(self.request({'text':'Привет','style':'Кратко'}),(200,{'action':'reply','reply':'Привет!'}))
            body=json.loads(provider.call_args.args[0].data)
            self.assertEqual(len(body['messages']),2)
            self.assertNotIn('tools',body)
    def test_review_never_becomes_reply(self):
        with patch.object(gateway.urllib.request,'urlopen',return_value=self.provider({'action':'review','reply':'опасное предложение'})):
            self.assertEqual(self.request({'text':'важный вопрос'})[1],{'action':'review','reply':''})
    def test_malformed_provider_response_fails_closed(self):
        with patch.object(gateway.urllib.request,'urlopen',return_value=io.BytesIO(b'not json')):
            self.assertEqual(self.request({'text':'hello'})[0],502)
    def test_provider_failure_fails_closed(self):
        with patch.object(gateway.urllib.request,'urlopen',side_effect=TimeoutError()):
            self.assertEqual(self.request({'text':'hello'}),(502,{'action':'review','reply':''}))
    def test_rate_limit(self):
        gateway.Gateway.window=__import__('time').monotonic()
        gateway.Gateway.calls=60
        with patch.object(gateway.urllib.request,'urlopen') as provider:
            self.assertEqual(self.request({'text':'hello'})[0],429)
            provider.assert_not_called()
    def test_reply_length(self):
        with patch.object(gateway.urllib.request,'urlopen',return_value=self.provider({'action':'reply','reply':'x'*1501})):
            self.assertEqual(self.request({'text':'hello'})[1]['action'],'review')

    def test_transcription_requires_auth(self):
        self.assertEqual(self.request(b'voice',token='wrong',path='/transcribe',content_type='audio/ogg')[0],401)
    def test_transcription_rejects_unsupported_type(self):
        self.assertEqual(self.request(b'voice',path='/transcribe',content_type='application/octet-stream')[0],415)
    def test_transcription_uploads_recording_as_multipart(self):
        with patch.object(gateway.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps({'text':'Привет из записи'}).encode())) as provider:
            self.assertEqual(self.request(b'OggS-example',path='/transcribe',content_type='audio/ogg'),(200,{'text':'Привет из записи'}))
            request=provider.call_args.args[0]
            self.assertEqual(request.full_url,'https://api.openai.com/v1/audio/transcriptions')
            self.assertIn(b'filename="recording.ogg"',request.data)
            self.assertIn(b'OggS-example',request.data)
    def test_transcription_video_notes(self):
        with patch.object(gateway.urllib.request,'urlopen',return_value=io.BytesIO(b'{"text":"video note"}')) as provider:
            self.assertEqual(self.request(b'video-bytes',path='/transcribe',content_type='video/mp4')[1]['text'],'video note')
            self.assertIn(b'filename="recording.mp4"',provider.call_args.args[0].data)
    def test_transcription_failure_does_not_expose_provider_error(self):
        with patch.object(gateway.urllib.request,'urlopen',side_effect=TimeoutError('secret response')):
            code,result=self.request(b'voice',path='/transcribe',content_type='audio/ogg')
            self.assertEqual(code,502)
            self.assertNotIn('secret',str(result))
    def test_transcription_rejects_empty_recording(self):
        self.assertEqual(self.request(b'',path='/transcribe',content_type='audio/ogg')[0],413)
    def test_transcription_shares_rate_limit(self):
        gateway.Gateway.window=__import__('time').monotonic()
        gateway.Gateway.calls=60
        with patch.object(gateway.urllib.request,'urlopen') as provider:
            self.assertEqual(self.request(b'voice',path='/transcribe',content_type='audio/ogg')[0],429)
            provider.assert_not_called()

if __name__=='__main__':unittest.main()
