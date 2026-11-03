import contextlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
from business import phone
from business.bot import Config

TOKEN='123456:'+'t'*30
KEY='test-provider-key-never-print'

class PhoneTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();base=Path(self.temp.name)
        self.paths=phone.Paths(base/'private/config.json',base/'private-data')
        self.values={'TELEGRAM_BOT_TOKEN':TOKEN,'TELEGRAM_OWNER_ID':'0','OPENAI_API_KEY':'','STATE_PATH':str(self.paths.data/'state.sqlite3')}
    def tearDown(self):self.temp.cleanup()
    def test_private_config_permissions_and_roundtrip(self):
        phone.write_config(self.paths,self.values)
        self.assertEqual(phone.read_config(self.paths),self.values)
        self.assertEqual(stat.S_IMODE(self.paths.config.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(self.paths.config.parent.stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE(self.paths.data.stat().st_mode),0o700)
    def test_first_setup_masks_secrets_and_needs_no_ai_key(self):
        secret=Mock(return_value=TOKEN);answers=iter(['','']);out=[]
        phone.setup(self.paths,prompt=lambda _:next(answers),secret=secret,output=out.append)
        self.assertEqual(secret.call_count,1)
        self.assertEqual(phone.read_config(self.paths)['TELEGRAM_OWNER_ID'],'0')
        self.assertNotIn(TOKEN,'\n'.join(out))
    def test_activation_reuses_token_without_echo(self):
        phone.write_config(self.paths,self.values)
        secrets=iter(['',KEY]);answers=iter(['100','коротко и на ты']);out=[]
        phone.setup(self.paths,prompt=lambda _:next(answers),secret=lambda _:next(secrets),output=out.append)
        values=phone.read_config(self.paths);self.assertEqual(values['TELEGRAM_BOT_TOKEN'],TOKEN)
        self.assertEqual(values['OPENAI_API_KEY'],KEY);self.assertEqual(values['TELEGRAM_OWNER_ID'],'100')
        self.assertNotIn(KEY,'\n'.join(out));self.assertNotIn(TOKEN,'\n'.join(out))
    def test_missing_ai_key_does_not_replace_good_config(self):
        phone.write_config(self.paths,self.values);before=self.paths.config.read_bytes()
        secrets=iter(['','']);answers=iter(['100',''])
        with self.assertRaises(ValueError):phone.setup(self.paths,prompt=lambda _:next(answers),secret=lambda _:next(secrets),output=lambda _:None)
        self.assertEqual(self.paths.config.read_bytes(),before)
    def test_malformed_id_does_not_write_secrets(self):
        with self.assertRaises(ValueError):phone.setup(self.paths,prompt=lambda _:'not-a-number',secret=lambda _:TOKEN,output=lambda _:None)
        self.assertFalse(self.paths.config.exists())
    def test_second_instance_and_setup_are_blocked(self):
        with phone.single_instance(self.paths):
            with self.assertRaises(ValueError):
                with phone.single_instance(self.paths):pass
            secret=Mock(return_value=TOKEN)
            with self.assertRaises(ValueError):phone.setup(self.paths,secret=secret,output=lambda _:None)
            secret.assert_not_called()
    def test_run_uses_private_state_and_does_not_export_secrets(self):
        values={**self.values,'STATE_PATH':'/sdcard/unsafe.sqlite3'};phone.write_config(self.paths,values)
        serve=Mock();out=[]
        with patch.dict(os.environ,{'TELEGRAM_OWNER_ID':'999'},clear=True),patch.object(phone,'wake_lock',return_value=contextlib.nullcontext(False)):
            phone.run(self.paths,serve=serve,output=out.append)
            self.assertEqual(os.environ['TELEGRAM_OWNER_ID'],'999')
            self.assertNotIn('TELEGRAM_BOT_TOKEN',os.environ)
        passed=serve.call_args.args[0]
        self.assertEqual(passed['STATE_PATH'],str(self.paths.data/'state.sqlite3'))
        self.assertEqual(passed['TELEGRAM_OWNER_ID'],'0')
        self.assertNotIn(TOKEN,'\n'.join(out))
    def test_config_values_are_independent_of_process_environment(self):
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'wrong','TELEGRAM_OWNER_ID':'999'},clear=True):
            self.assertEqual(Config.env(self.values).bot_token,TOKEN)
            self.assertEqual(Config.env(self.values).owner_id,0)
    def test_insecure_file_permissions_are_rejected(self):
        phone.write_config(self.paths,self.values);self.paths.config.chmod(0o644)
        with self.assertRaises(ValueError):phone.read_config(self.paths)
    def test_corrupt_file_error_does_not_echo_secret(self):
        phone.write_config(self.paths,self.values);self.paths.config.write_text('{"token":"'+TOKEN)
        with self.assertRaises(ValueError) as error:phone.read_config(self.paths)
        self.assertNotIn(TOKEN,str(error.exception))
    def test_unknown_settings_rejected(self):
        phone.write_config(self.paths,self.values)
        self.paths.config.write_text(json.dumps({**self.values,'SHELL_COMMAND':'bad'}))
        with self.assertRaises(ValueError):phone.read_config(self.paths)
    def test_forget_requires_explicit_confirmation(self):
        phone.write_config(self.paths,self.values);state=self.paths.data/'state.sqlite3';state.write_bytes(b'test')
        phone.forget(self.paths,prompt=lambda _:'нет',output=lambda _:None);self.assertTrue(self.paths.config.exists())
        phone.forget(self.paths,prompt=lambda _:'да',output=lambda _:None);self.assertFalse(self.paths.config.exists());self.assertTrue(state.exists())
    def test_wake_lock_released_after_failure(self):
        with patch.object(phone.shutil,'which',side_effect=lambda n:'/bin/'+n),patch.object(phone.subprocess,'run',return_value=Mock(returncode=0)) as run:
            with self.assertRaises(RuntimeError):
                with phone.wake_lock():raise RuntimeError('simulated stop')
            self.assertEqual([c.args[0][0] for c in run.call_args_list],['/bin/termux-wake-lock','/bin/termux-wake-unlock'])
    def test_cancelled_setup_does_not_save_token(self):
        with self.assertRaises(KeyboardInterrupt):phone.setup(self.paths,prompt=Mock(side_effect=KeyboardInterrupt),secret=lambda _:TOKEN,output=lambda _:None)
        self.assertFalse(self.paths.config.exists())
