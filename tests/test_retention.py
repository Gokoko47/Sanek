"""Exercise the real deletion filter against small in-memory Android/Telegram adapters."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

FIXTURES={
'android/content/SharedPreferences.java':'''package android.content;
import java.util.*;
public interface SharedPreferences {boolean getBoolean(String k,boolean d);long getLong(String k,long d);Map<String,?> getAll();Editor edit();interface Editor {Editor putBoolean(String k,boolean v);Editor putLong(String k,long v);Editor remove(String k);Editor clear();void apply();}}''',
'android/content/Context.java':'''package android.content;
import java.util.*;
public class Context {private final Map<String,SharedPreferences> all=new HashMap<>();public SharedPreferences getSharedPreferences(String n,int mode){return all.computeIfAbsent(n,k->new Prefs());}private static class Prefs implements SharedPreferences {private final Map<String,Object> data=new HashMap<>();public boolean getBoolean(String k,boolean d){return data.containsKey(k)?(Boolean)data.get(k):d;}public long getLong(String k,long d){return data.containsKey(k)?(Long)data.get(k):d;}public Map<String,?> getAll(){return new HashMap<>(data);}public Editor edit(){return new Editor(){Map<String,Object> changes=new HashMap<>();boolean clear;public Editor putBoolean(String k,boolean v){changes.put(k,v);return this;}public Editor putLong(String k,long v){changes.put(k,v);return this;}public Editor remove(String k){changes.put(k,null);return this;}public Editor clear(){clear=true;return this;}public void apply(){if(clear)data.clear();for(Map.Entry<String,Object> e:changes.entrySet())if(e.getValue()==null)data.remove(e.getKey());else data.put(e.getKey(),e.getValue());}};}}}''',
'org/telegram/messenger/ApplicationLoader.java':'''package org.telegram.messenger;public class ApplicationLoader {public static android.content.Context applicationContext=new android.content.Context();}''',
'org/telegram/messenger/UserConfig.java':'''package org.telegram.messenger;public class UserConfig {public static final int MAX_ACCOUNT_COUNT=4;}''',
'org/telegram/messenger/DialogObject.java':'''package org.telegram.messenger;public class DialogObject {public static boolean isEncryptedDialog(long d){return d>0&&(d&0xffffffffL)==0;}}''',
'org/telegram/messenger/MessageObject.java':'''package org.telegram.messenger;import org.telegram.tgnet.TLRPC;public class MessageObject {public TLRPC.Message messageOwner;public boolean scheduled;public static long getDialogId(TLRPC.Message m){return m.dialog_id;}}''',
'org/telegram/tgnet/TLRPC.java':'''package org.telegram.tgnet;public class TLRPC {public static class Peer{public long channel_id;}public static class Media{public int ttl_seconds;}public static class Message{public int id,ttl_period;public boolean out,noforwards;public long dialog_id;public Peer peer_id=new Peer();public Media media;}public static class TL_message extends Message{}}''',
'org/telegram/messenger/pakostnik/RetainedMedia.java':'''package org.telegram.messenger.pakostnik;import org.telegram.tgnet.TLRPC;public class RetainedMedia{private static final RetainedMedia media=new RetainedMedia();public static RetainedMedia get(int a){return media;}public void remember(org.telegram.messenger.MessageObject m){}public void forget(String k){}public void clear(){}}''',
'org/telegram/messenger/pakostnik/RetentionTest.java':'''package org.telegram.messenger.pakostnik;
import org.telegram.tgnet.TLRPC;import java.util.*;
public class RetentionTest{
 static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
 static TLRPC.TL_message msg(int id,long dialog,long channel){TLRPC.TL_message m=new TLRPC.TL_message();m.id=id;m.dialog_id=dialog;m.peer_id.channel_id=channel;return m;}
 public static void main(String[] args)throws Exception{
  RetainedMessages a=RetainedMessages.get(0);check(a.enabled(),"default enabled");
  TLRPC.TL_message text=msg(10,123,0);a.remember(text);check(a.filterRemote(0,Arrays.asList(10)).isEmpty(),"incoming survives");check(a.deleted(text),"cross marker");
  check(a.filterRemote(0,Arrays.asList(999)).equals(Arrays.asList(999)),"unknown must be deleted normally");
  TLRPC.TL_message channel=msg(10,-200,200);a.remember(channel);check(!a.deleted(channel),"channel IDs isolated");a.filterRemote(200,Arrays.asList(10));check(a.deleted(channel),"channel deletion marked");
  TLRPC.TL_message group=msg(11,-456,0);a.remember(group);check(a.filterRemote(0,Arrays.asList(11)).isEmpty(),"basic group survives");
  TLRPC.TL_message own=msg(12,123,0);own.out=true;a.remember(own);check(a.filterRemote(0,Arrays.asList(12)).contains(12),"own outgoing not retained");
  TLRPC.TL_message timer=msg(13,123,0);timer.ttl_period=60;a.remember(timer);check(a.filterRemote(0,Arrays.asList(13)).contains(13),"expiry respected");
  TLRPC.TL_message viewOnce=msg(14,123,0);viewOnce.media=new TLRPC.Media();viewOnce.media.ttl_seconds=1;a.remember(viewOnce);check(a.filterRemote(0,Arrays.asList(14)).contains(14),"view once excluded");
  TLRPC.TL_message protectedMessage=msg(15,123,0);protectedMessage.noforwards=true;a.remember(protectedMessage);check(a.filterRemote(0,Arrays.asList(15)).contains(15),"protected excluded");
  TLRPC.TL_message secret=msg(16,1L<<32,0);a.remember(secret);check(a.filterRemote(0,Arrays.asList(16)).contains(16),"secret excluded");
  TLRPC.TL_message login=msg(17,777000,0);a.remember(login);check(a.filterRemote(0,Arrays.asList(17)).contains(17),"login service excluded");
  a.forgetLocal(123,Arrays.asList(10));check(!a.deleted(text)&&a.filterRemote(0,Arrays.asList(10)).contains(10),"explicit deletion honored");check(a.deleted(channel),"local deletion doesn't affect channel collision");
  a.enabled(false);TLRPC.TL_message off=msg(18,123,0);a.remember(off);check(a.filterRemote(0,Arrays.asList(18)).contains(18),"disabled behavior");a.enabled(true);
  a.forgetDialog(-200);check(!a.deleted(channel),"clear history honored");
  check(!RetainedMessages.get(1).deleted(group),"accounts isolated");
  java.lang.reflect.Field field=RetainedMessages.class.getDeclaredField("all");field.setAccessible(true);((RetainedMessages[])field.get(null))[0]=null;RetainedMessages reloaded=RetainedMessages.get(0);check(reloaded.deleted(group),"marker survives instance recreation");
  reloaded.clear();check(!reloaded.deleted(group),"logout clears retention");
  System.out.println("Retention scenarios OK");
 }
}'''
}

class RetentionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('java'),'JDK required')
    def test_remote_deletion_markers_and_local_controls(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for name,source in FIXTURES.items():
                f=folder/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(source)
            java_files=list(folder.rglob('*.java'))+[root/'overlay/TMessagesProj/src/main/java/org/telegram/messenger/pakostnik/RetainedMessages.java']
            compiler=['javac'] if shutil.which('javac') else ['java','-m','jdk.compiler/com.sun.tools.javac.Main']
            subprocess.run([*compiler,'-d',tmp,*map(str,java_files)],check=True,capture_output=True,text=True)
            result=subprocess.run(['java','-cp',tmp,'org.telegram.messenger.pakostnik.RetentionTest'],check=True,capture_output=True,text=True)
            self.assertIn('Retention scenarios OK',result.stdout)
