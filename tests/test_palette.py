"""Validate actual color parsing and readability rules without an Android device."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

class PaletteTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('java'),'JDK required')
    def test_color_profiles_remain_readable(self):
        root=Path(__file__).resolve().parents[1]
        test='''package org.telegram.messenger.pakostnik;
public class PaletteTest {
 static void check(boolean b,String s){if(!b)throw new AssertionError(s);}
 static void reject(String s){try{ConsolePalette.parse(s);throw new AssertionError("accepted "+s);}catch(IllegalArgumentException expected){}}
 public static void main(String[] args){
  check(ConsolePalette.parse("#000000")==0xff000000,"black");
  check(ConsolePalette.parse("f2f2f2")==0xfff2f2f2,"optional hash");
  check(ConsolePalette.hex(0xff1234ab).equals("#1234AB"),"format");
  check(Math.abs(ConsolePalette.contrast(0xff000000,0xffffffff)-21)<.001,"contrast");
  check(Math.abs(ConsolePalette.contrast(0xff888888,0xff888888)-1)<.001,"same color");
  ConsolePalette.validate(0xff000000,0xfff2f2f2);
  ConsolePalette.validate(0xff101010,0xffeeeeee);
  ConsolePalette.validate(0xff000000,0xffa6ff80);
  try{ConsolePalette.validate(0xff000000,0xff121212);throw new AssertionError("invisible accent");}catch(IllegalArgumentException expected){}
  try{ConsolePalette.validate(0xffeeeeee,0xff000000);throw new AssertionError("bright backdrop");}catch(IllegalArgumentException expected){}
  for(String s:new String[]{"#12","#GGGGGG","#FFFFFFFF","red",""})reject(s);
  int gray=ConsolePalette.gray(0x8012a3ef);check((gray>>>24)==0x80,"alpha");check(((gray>>16)&255)==((gray>>8)&255)&&((gray>>8)&255)==(gray&255),"monochrome");
  check(ConsolePalette.surface(0xff000000,.065)==0xff101010,"panel");
  System.out.println("Console palette OK");
 }
}'''
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'PaletteTest.java';f.write_text(test)
            compiler=['javac'] if shutil.which('javac') else ['java','-m','jdk.compiler/com.sun.tools.javac.Main']
            source=root/'overlay/TMessagesProj/src/main/java/org/telegram/messenger/pakostnik/ConsolePalette.java'
            subprocess.run([*compiler,'-d',tmp,str(source),str(f)],check=True,capture_output=True,text=True)
            result=subprocess.run(['java','-cp',tmp,'org.telegram.messenger.pakostnik.PaletteTest'],check=True,capture_output=True,text=True)
            self.assertIn('Console palette OK',result.stdout)
