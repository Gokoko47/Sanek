package org.telegram.messenger.pakostnik;

import android.content.SharedPreferences;
import org.telegram.messenger.*;
import org.telegram.tgnet.TLRPC;
import java.util.*;

/** Filters remote deletion only. Explicit local deletion and history clearing still work. */
public final class RetainedMessages {
 private static final RetainedMessages[] all=new RetainedMessages[UserConfig.MAX_ACCOUNT_COUNT];
 public static synchronized RetainedMessages get(int account){if(all[account]==null)all[account]=new RetainedMessages(account);return all[account];}
 private final int account;
 private final SharedPreferences prefs;
 private RetainedMessages(int account){this.account=account;prefs=ApplicationLoader.applicationContext.getSharedPreferences("pakostnik_retained_"+account,0);}
 public boolean enabled(){return prefs.getBoolean("enabled",true);}
 public void enabled(boolean value){prefs.edit().putBoolean("enabled",value).apply();}
 public static String key(long channel,int id){return channel+"_"+id;}
 public static String key(TLRPC.Message m){return key(m.peer_id==null?0:m.peer_id.channel_id,m.id);}
 public void remember(TLRPC.Message m){
  if(m==null||!enabled())return;
  String key=key(m);
  long dialog=MessageObject.getDialogId(m);
  if(!(m instanceof TLRPC.TL_message)||m.id<=0||m.out||dialog==0||dialog==777000||DialogObject.isEncryptedDialog(dialog)||m.ttl_period!=0||m.noforwards||(m.media!=null&&m.media.ttl_seconds!=0)){
   // Revocation of eligibility (for example, an expiry timer) must not leave a stale exemption.
   boolean wasKnown=known(key);prefs.edit().remove("known_"+key).remove("deleted_"+key).apply();if(wasKnown)RetainedMedia.get(account).forget(key);return;
  }
  prefs.edit().putLong("known_"+key,dialog).apply();
 }
 public void remember(MessageObject m){if(m==null||m.messageOwner==null||m.scheduled)return;remember(m.messageOwner);if(known(key(m.messageOwner)))RetainedMedia.get(account).remember(m);}
 public boolean known(String key){return prefs.getLong("known_"+key,0)!=0;}
 public ArrayList<Integer> filterRemote(long channel,List<Integer> ids){
  ArrayList<Integer> delete=new ArrayList<>();SharedPreferences.Editor edit=prefs.edit();
  for(Integer id:ids){String key=key(channel,id);if(enabled()&&known(key)){edit.putBoolean("deleted_"+key,true);}else delete.add(id);}
  edit.apply();return delete;
 }
 public boolean deleted(TLRPC.Message m){return m!=null&&prefs.getBoolean("deleted_"+key(m),false);}
 public void forgetLocal(long dialog,List<Integer> ids){if(ids==null)return;SharedPreferences.Editor edit=prefs.edit();for(Map.Entry<String,?> e:prefs.getAll().entrySet()){if(!e.getKey().startsWith("known_")||!(e.getValue() instanceof Long)||((Long)e.getValue()).longValue()!=dialog)continue;String key=e.getKey().substring(6);int split=key.lastIndexOf('_');try{if(ids.contains(Integer.parseInt(key.substring(split+1)))){edit.remove("known_"+key).remove("deleted_"+key);RetainedMedia.get(account).forget(key);}}catch(NumberFormatException ignored){}}edit.apply();}
 public void forgetDialog(long dialog){SharedPreferences.Editor edit=prefs.edit();for(Map.Entry<String,?> e:prefs.getAll().entrySet())if(e.getKey().startsWith("known_")&&e.getValue() instanceof Long&&((Long)e.getValue()).longValue()==dialog){String key=e.getKey().substring(6);edit.remove(e.getKey()).remove("deleted_"+key);RetainedMedia.get(account).forget(key);}edit.apply();}
 public void clear(){prefs.edit().clear().apply();RetainedMedia.get(account).clear();}
}
