"""Run the real Android-side text filter in a plain JVM (no provider requests)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

class TextSafetyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('java'), 'JDK required for Java filter checks')
    def test_sensitive_and_casual_messages(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            sources=[root/'tests/java/SafetyTest.java',root/'overlay/TMessagesProj/src/main/java/org/telegram/messenger/pakostnik/Safety.java']
            compiler=['javac'] if shutil.which('javac') else ['java','-m','jdk.compiler/com.sun.tools.javac.Main']
            subprocess.run([*compiler,'-d',directory,*map(str,sources)],check=True,capture_output=True,text=True)
            result=subprocess.run(['java','-cp',directory,'org.telegram.messenger.pakostnik.SafetyTest'],check=True,capture_output=True,text=True)
            self.assertIn('12 cases OK',result.stdout)
