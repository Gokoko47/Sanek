package org.telegram.messenger.pakostnik;

import org.json.*;
import org.telegram.messenger.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Bounded, encrypted, device-only cache of incoming plain text. Never restores server data. */
public final class LocalArchive {
 private static final LocalArchive[] all=new LocalArchive[UserConfig.MAX_ACCOUNT_COUNT];
 public static synchronized LocalArchive get(int account){if(all[account]==null)all[account]=new LocalArchive(account);return all[account];}
 private final int account;
 private final SecretStore store;
 private final android.content.SharedPreferences prefs;
 private final ThreadPoolExecutor worker=new ThreadPoolExecutor(1,1,0,TimeUnit.SECONDS,new ArrayBlockingQueue<>(128),new ThreadPoolExecutor.DiscardPolicy());
 private JSONArray entries;
 private LocalArchive(int a){account=a;store=new SecretStore(ApplicationLoader.applicationContext);prefs=ApplicationLoader.applicationContext.getSharedPreferences("pakostnik_archive_"+a,0);}
 public boolean enabled(){return prefs.getBoolean("enabled",true);}
 public void enabled(boolean value){prefs.edit().putBoolean("enabled",value).commit();if(!value)clear();}
 private void load()throws Exception{if(entries==null){String raw=store.get("archive_"+account);entries=raw.isEmpty()?new JSONArray():new JSONArray(raw);}}
 private void save()throws Exception{JSONArray kept=new JSONArray();long cutoff=System.currentTimeMillis()/1000-7*86400;for(int i=Math.max(0,entries.length()-500);i<entries.length();i++){JSONObject e=entries.getJSONObject(i);if(e.optLong("date")>=cutoff)kept.put(e);}entries=kept;store.set("archive_"+account,entries.toString());}
 public void record(MessageObject m){
  if(!enabled()||m==null||m.messageOwner==null||m.isOutOwner()||m.getId()<=0||m.type!=MessageObject.TYPE_TEXT||m.getDialogId()<=0||m.getDialogId()==777000||DialogObject.isEncryptedDialog(m.getDialogId())||m.messageOwner.ttl_period!=0||m.messageOwner.noforwards)return;
  String text=m.messageOwner.message;if(text==null||text.isEmpty())return;
  final String snapshot=text.substring(0,Math.min(text.length(),4000));final int id=m.getId(),date=m.messageOwner.date;final long chat=m.getDialogId();
  if(System.currentTimeMillis()/1000-date>7*86400)return;
  worker.execute(()->{try{if(!enabled())return;load();for(int i=0;i<entries.length();i++)if(entries.getJSONObject(i).optInt("id")==id)return;entries.put(new JSONObject().put("id",id).put("chat",chat).put("date",date).put("text",snapshot).put("deleted",false));save();}catch(Exception ignored){}});
 }
 public void deleted(ArrayList<Integer> ids){if(!enabled())return;HashSet<Integer> copy=new HashSet<>(ids);worker.execute(()->{try{load();for(int i=0;i<entries.length();i++){JSONObject e=entries.getJSONObject(i);if(copy.contains(e.optInt("id")))e.put("deleted",true);}save();}catch(Exception ignored){}});}
 public void readDeleted(Consumer<String> callback){readDeleted(0,callback);}
 public void readDeleted(long dialog,Consumer<String> callback){worker.execute(()->{StringBuilder text=new StringBuilder();try{load();save();for(int i=entries.length()-1;i>=0;i--){JSONObject e=entries.getJSONObject(i);if(!e.optBoolean("deleted")||(dialog!=0&&e.optLong("chat")!=dialog))continue;text.append("Чат ").append(e.optLong("chat")).append(" · ").append(new java.util.Date(e.optLong("date")*1000)).append("\n").append(e.optString("text")).append("\n\n");if(text.length()>60000)break;}}catch(Exception ignored){}String result=text.length()==0?"Сохранённых удалённых сообщений пока нет.":text.toString();AndroidUtilities.runOnUIThread(()->callback.accept(result));});}
 public void forgetLocal(long dialog,List<Integer> ids){HashSet<Integer> copy=ids==null?null:new HashSet<>(ids);worker.execute(()->{try{load();JSONArray kept=new JSONArray();for(int i=0;i<entries.length();i++){JSONObject e=entries.getJSONObject(i);if(e.optLong("chat")==dialog&&(copy==null||copy.contains(e.optInt("id"))))continue;kept.put(e);}entries=kept;save();}catch(Exception ignored){}});}
 public void clear(){worker.getQueue().clear();worker.execute(()->{try{entries=new JSONArray();store.set("archive_"+account,"[]");}catch(Exception ignored){}});}
}
