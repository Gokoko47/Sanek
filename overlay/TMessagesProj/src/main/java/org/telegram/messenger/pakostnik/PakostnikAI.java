package org.telegram.messenger.pakostnik;

import android.content.SharedPreferences;
import org.json.JSONObject;
import org.telegram.messenger.*;
import org.telegram.tgnet.*;
import java.net.URI;
import javax.net.ssl.HttpsURLConnection;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

/** All state mutations and Telegram calls run on Telegram's UI thread. */
public final class PakostnikAI {
 public static final String NOTICE="Pakostnik AI: в этой переписке включён ИИ-помощник. Новые текстовые сообщения передаются моему настроенному ИИ-сервису. Для отключения напишите /stop.";
 private static final PakostnikAI[] instances=new PakostnikAI[UserConfig.MAX_ACCOUNT_COUNT];
 public static synchronized PakostnikAI get(int account){if(instances[account]==null)instances[account]=new PakostnikAI(account);return instances[account];}
 private final int account;
 private final SharedPreferences prefs;
 final SecretStore vault;
 private final ExecutorService executor=new ThreadPoolExecutor(1,1,0L,TimeUnit.MILLISECONDS,new ArrayBlockingQueue<>(8),new ThreadPoolExecutor.AbortPolicy());
 private final Map<Long,String> drafts=new HashMap<>();
 private final Map<Long,Long> draftTime=new HashMap<>();
 private final Map<Long,Long> lastReply=new HashMap<>();
 private final Map<Long,Integer> latest=new HashMap<>();
 private final Set<Long> active=new HashSet<>();
 private boolean enabled;
 private long epoch, started, hour;
 private int sent;
 private boolean internalSend;
 private String status="ИИ выключен. После перезапуска включите вручную.";
 private PakostnikAI(int account){this.account=account;prefs=ApplicationLoader.applicationContext.getSharedPreferences("pakostnik_"+account,0);vault=new SecretStore(ApplicationLoader.applicationContext);started=System.currentTimeMillis()/1000;}
 public String status(){return status;}
 public boolean enabled(){return enabled;}
 public int mode(long dialog){return prefs.getInt("mode_"+dialog,0);}
 public String draft(long dialog){if(System.currentTimeMillis()/1000-draftTime.getOrDefault(dialog,0L)>120){drafts.remove(dialog);}return drafts.get(dialog);}
 public String setting(String name){return vault.get(account+"_"+name);}
 public void configure(String endpoint,String token,String style) throws Exception {
  URI u=URI.create(endpoint);if(!"https".equalsIgnoreCase(u.getScheme())||u.getHost()==null||u.getUserInfo()!=null||token.length()<32||style.length()>300)throw new IllegalArgumentException();
  enable(false);vault.set(account+"_endpoint",endpoint);vault.set(account+"_token",token);vault.set(account+"_style",style);
 }
 public void enable(boolean value){epoch++;enabled=value;started=System.currentTimeMillis()/1000;active.clear();drafts.clear();status=value?"ИИ включён. Выберите режим нужного чата.":"ИИ остановлен во всех чатах этого аккаунта.";}
 public void stopAll(){for(PakostnikAI instance:instances)if(instance!=null)instance.enable(false);}
 public boolean eligible(long dialog){
  if(dialog<=0||DialogObject.isEncryptedDialog(dialog)||!UserConfig.getInstance(account).isClientActivated()||dialog==UserConfig.getInstance(account).getClientUserId()||dialog==777000)return false;
  TLRPC.User u=MessagesController.getInstance(account).getUser(dialog);
  return u!=null&&!u.bot&&!u.deleted&&!u.support&&MessagesController.getInstance(account).getSendPaidMessagesStars(dialog)==0;
 }
 public void choose(long dialog,int mode){
  epoch++;active.remove(dialog);drafts.remove(dialog);
  prefs.edit().putInt("mode_"+dialog,mode).commit();
  if(mode==0){status="Ручной режим";return;}
  if(!enabled||!eligible(dialog)){status="Сначала включите ИИ. Доступны личные чаты с людьми без оплаты сообщений.";return;}
  send(dialog,NOTICE);
  active.add(dialog);
  status="ИИ активен в выбранном чате. Ответит на новые сообщения.";
 }
 public void onDeleted(ArrayList<Integer> ids){HashSet<Integer> deleted=new HashSet<>(ids);boolean changed=false;Iterator<Map.Entry<Long,Integer>> it=latest.entrySet().iterator();while(it.hasNext()){Map.Entry<Long,Integer> e=it.next();if(deleted.contains(e.getValue())){drafts.remove(e.getKey());it.remove();changed=true;}}if(changed)epoch++;}
 public void manualSend(long dialog){if(!internalSend){epoch++;drafts.remove(dialog);status="Ручная отправка отменила ожидающие автоответы.";}}
 public void onMessages(ArrayList<MessageObject> batch,boolean scheduled,int mode){
  if(scheduled||mode!=0||batch==null)return;
  for(MessageObject m:batch){
   if(m==null||m.messageOwner==null||m.getId()<=0)continue;
   RetainedMessages.get(account).remember(m);
   LocalArchive.get(account).record(m);
   VoiceTranscriber.remember(account,m);
   long dialog=m.getDialogId();
   if(m.isOutOwner()){if(m.messageOwner.date>=started&&m.messageOwner.message!=null&&!(m.messageOwner.params!=null&&"1".equals(m.messageOwner.params.get("pakostnik_ai")))&&!NOTICE.equals(m.messageOwner.message))manualSend(dialog);continue;}
   String text=m.messageOwner.message;
   if(text==null||m.type!=MessageObject.TYPE_TEXT||text.isEmpty()||m.messageOwner.date<started||System.currentTimeMillis()/1000-m.messageOwner.date>120||!eligible(dialog))continue;
   if(text.trim().equalsIgnoreCase("/stop")){choose(dialog,0);continue;}
   int selected=mode(dialog);
   if(!enabled||selected==0||!active.contains(dialog))continue;
   int id=m.getId();if(id<=prefs.getInt("seen_"+dialog,0))continue;
   prefs.edit().putInt("seen_"+dialog,id).commit();latest.put(dialog,id);drafts.remove(dialog);
   if(Safety.blocked(text)){status="Чувствительное сообщение: ответьте вручную.";continue;}
   long version=epoch;int date=m.messageOwner.date;
   try{executor.execute(()->request(dialog,id,text,version,selected,date));}catch(RejectedExecutionException e){status="Очередь ИИ заполнена. Ответьте вручную.";}
  }
 }
 private boolean valid(long dialog,int id,long version,int selected,int date){return enabled&&epoch==version&&mode(dialog)==selected&&active.contains(dialog)&&Objects.equals(latest.get(dialog),id)&&System.currentTimeMillis()/1000-date<120&&eligible(dialog);}
 private void request(long dialog,int id,String text,long version,int selected,int date){
  try{
   java.util.concurrent.FutureTask<Boolean> preflight=new java.util.concurrent.FutureTask<>(()->valid(dialog,id,version,selected,date));
   AndroidUtilities.runOnUIThread(preflight);
   if(!preflight.get(5,TimeUnit.SECONDS))return;
   // Secrets are read only by this worker. No Telegram history or attachments are sent.
   URI uri=URI.create(setting("endpoint"));if(!"https".equalsIgnoreCase(uri.getScheme())||uri.getHost()==null||uri.getUserInfo()!=null)throw new Exception();
   HttpsURLConnection c=(HttpsURLConnection)uri.toURL().openConnection();c.setInstanceFollowRedirects(false);c.setConnectTimeout(10000);c.setReadTimeout(45000);c.setRequestMethod("POST");c.setDoOutput(true);c.setRequestProperty("Authorization","Bearer "+setting("token"));c.setRequestProperty("Content-Type","application/json");
   JSONObject result;
   try{
    JSONObject payload=new JSONObject();payload.put("text",text);payload.put("style",setting("style"));
    try(java.io.OutputStream out=c.getOutputStream()){out.write(payload.toString().getBytes(StandardCharsets.UTF_8));}
    if(c.getResponseCode()!=200)throw new Exception();
    try(java.io.InputStream in=c.getInputStream();java.io.ByteArrayOutputStream out=new java.io.ByteArrayOutputStream()){
     byte[] buffer=new byte[2048];int n;while((n=in.read(buffer))!=-1){out.write(buffer,0,n);if(out.size()>16384)throw new Exception();}result=new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8));
    }
   }finally{c.disconnect();}
   String reply=result.optString("reply").trim();boolean safe=result.optString("action").equals("reply")&&!reply.isEmpty()&&reply.length()<=1500&&!Safety.blocked(reply);
   AndroidUtilities.runOnUIThread(()->{
    if(!valid(dialog,id,version,selected,date))return;
    if(!safe){status="Важный или неоднозначный вопрос: ответьте вручную.";return;}
    if(selected==1){drafts.put(dialog,reply);draftTime.put(dialog,System.currentTimeMillis()/1000);status="Предложение готово. Откройте Pakostnik AI в главном меню и выберите чат.";return;}
    long now=System.currentTimeMillis();if(now-hour>=3600000){hour=now;sent=0;}
    if(sent>=10||now-lastReply.getOrDefault(dialog,0L)<60000){status="Лимит автоответов. Ответьте вручную.";return;}
    lastReply.put(dialog,now);sent++;send(dialog,reply);status="Автоответ передан Telegram на отправку.";
   });
  }catch(Exception e){AndroidUtilities.runOnUIThread(()->status="ИИ недоступен. Ответ не отправлен.");}
 }
 private void send(long dialog,String text){internalSend=true;try{SendMessagesHelper.SendMessageParams params=SendMessagesHelper.SendMessageParams.of(text,dialog);params.params=new HashMap<>();params.params.put("pakostnik_ai","1");SendMessagesHelper.getInstance(account).sendMessage(params);}finally{internalSend=false;}}
 public void approve(long dialog){String text=draft(dialog);drafts.remove(dialog);epoch++;if(text!=null&&enabled&&active.contains(dialog)&&mode(dialog)==1&&eligible(dialog)){send(dialog,text);status="Подтверждённый ответ передан Telegram.";}}
 public void logout(){enable(false);RetainedMessages.get(account).clear();LocalArchive.get(account).clear();VoiceTranscriber.forget(account);prefs.edit().clear().commit();try{vault.set(account+"_token","");vault.set(account+"_endpoint","");vault.set(account+"_style","");}catch(Exception ignored){}}
}
