package org.telegram.messenger.pakostnik;

import org.telegram.messenger.*;
import org.json.JSONObject;
import javax.net.ssl.HttpsURLConnection;
import java.io.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Voice and video-note files are uploaded only after a user action. */
public final class VoiceTranscriber {
 private static final LinkedHashMap<String,MessageObject> recent=new LinkedHashMap<>();
 private static final ExecutorService worker=Executors.newSingleThreadExecutor();
 public static synchronized void remember(int account,MessageObject m){if(m==null||m.messageOwner==null||(!m.isVoice()&&!m.isRoundVideo())||m.getDialogId()<=0||DialogObject.isEncryptedDialog(m.getDialogId())||m.messageOwner.ttl_period!=0||(m.messageOwner.media!=null&&m.messageOwner.media.ttl_seconds!=0)||m.messageOwner.noforwards)return;recent.put(account+":"+m.getDialogId()+":"+m.getId(),m);while(recent.size()>100)recent.remove(recent.keySet().iterator().next());}
 public static synchronized ArrayList<MessageObject> messages(int account){ArrayList<MessageObject> result=new ArrayList<>();for(Map.Entry<String,MessageObject> e:recent.entrySet())if(e.getKey().startsWith(account+":"))result.add(e.getValue());Collections.reverse(result);return result;}
 public static synchronized void forget(int account){recent.keySet().removeIf(k->k.startsWith(account+":"));}
 public static void transcribe(int account,MessageObject m,Consumer<String> callback){
  File file=FileLoader.getInstance(account).getPathToMessage(m.messageOwner);
  if(!file.isFile()){callback.accept("Сначала скачайте голосовое или кружок в переписке.");return;}
  if(file.length()==0||file.length()>24*1024*1024){callback.accept("Для расшифровки нужен файл до 24 МБ.");return;}
  // Snapshot before leaving the UI thread; no media is uploaded automatically.
  String endpoint=PakostnikAI.get(account).setting("endpoint"),token=PakostnikAI.get(account).setting("token");boolean video=m.isRoundVideo();
  worker.execute(()->{String result;
   try{
    URI uri=URI.create(endpoint).resolve("transcribe");if(!"https".equalsIgnoreCase(uri.getScheme())||uri.getHost()==null||uri.getUserInfo()!=null||token.length()<32)throw new Exception();
    HttpsURLConnection c=(HttpsURLConnection)uri.toURL().openConnection();c.setInstanceFollowRedirects(false);c.setRequestMethod("POST");c.setDoOutput(true);c.setConnectTimeout(10000);c.setReadTimeout(90000);c.setFixedLengthStreamingMode(file.length());c.setRequestProperty("Authorization","Bearer "+token);c.setRequestProperty("Content-Type",video?"video/mp4":"audio/ogg");
    try{try(InputStream in=new FileInputStream(file);OutputStream out=c.getOutputStream()){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)out.write(b,0,n);}if(c.getResponseCode()!=200)throw new Exception();try(InputStream in=c.getInputStream();ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] b=new byte[4096];int n;while((n=in.read(b))!=-1){out.write(b,0,n);if(out.size()>262144)throw new Exception();}result=new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8)).optString("text");if(result.isEmpty())result="Речь не распознана.";}}finally{c.disconnect();}
   }catch(Exception e){result="Не удалось расшифровать запись. Проверьте подключение к серверу и доступность файла.";}
   String text=result;AndroidUtilities.runOnUIThread(()->callback.accept(text));
  });
 }
}
