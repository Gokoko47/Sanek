package org.telegram.messenger.pakostnik;

import android.content.SharedPreferences;
import org.telegram.messenger.*;
import org.telegram.tgnet.TLRPC;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;

/** Private copies of media already downloaded by Telegram; does not fetch inaccessible files. */
public final class RetainedMedia {
 private static final RetainedMedia[] all=new RetainedMedia[UserConfig.MAX_ACCOUNT_COUNT];
 public static synchronized RetainedMedia get(int a){if(all[a]==null)all[a]=new RetainedMedia(a);return all[a];}
 private final int account;
 private final SharedPreferences prefs;
 private final File directory;
 private final ThreadPoolExecutor worker=new ThreadPoolExecutor(1,1,0,TimeUnit.SECONDS,new ArrayBlockingQueue<>(64),new ThreadPoolExecutor.DiscardPolicy());
 private RetainedMedia(int a){account=a;prefs=ApplicationLoader.applicationContext.getSharedPreferences("pakostnik_media_"+a,0);directory=new File(ApplicationLoader.applicationContext.getFilesDir(),"retained_media_"+a);}
 public boolean downloadEnabled(){return prefs.getBoolean("auto_download",true);}
 public void downloadEnabled(boolean enabled){prefs.edit().putBoolean("auto_download",enabled).apply();}
 public void remember(MessageObject parent){TLRPC.Message m=parent.messageOwner;if(m==null||m.media==null)return;String key=RetainedMessages.key(m);if(!RetainedMessages.get(account).known(key))return;File existing=backup(key);if(existing!=null){restoreOriginal(key,existing);return;}File source=FileLoader.getInstance(account).getPathToMessage(m);if(source==null||source.getName().isEmpty())return;prefs.edit().putString("source_"+key,source.getAbsolutePath()).apply();if(source.isFile())pin(key,source);else if(downloadEnabled()&&System.currentTimeMillis()/1000-m.date<=120&&!RetainedMessages.get(account).deleted(m)){
   TLRPC.Document document=MessageObject.getDocument(m);
   if(document!=null)FileLoader.getInstance(account).loadFile(document,parent,FileLoader.PRIORITY_LOW,0);
   else if(m.media.photo!=null){TLRPC.PhotoSize size=FileLoader.getClosestPhotoSizeWithSize(m.media.photo.sizes,AndroidUtilities.getPhotoSize());if(size!=null)FileLoader.getInstance(account).loadFile(ImageLocation.getForPhoto(size,m.media.photo),parent,"jpg",FileLoader.PRIORITY_LOW,0);}
  }}
 public void loaded(File source,Object parent){if(parent instanceof MessageObject)RetainedMessages.get(account).remember((MessageObject)parent);if(source==null)return;for(Map.Entry<String,?> e:prefs.getAll().entrySet())if(e.getKey().startsWith("source_")&&source.getAbsolutePath().equals(e.getValue()))pin(e.getKey().substring(7),source);}
 private void pin(String key,File source){worker.execute(()->{File partial=null;try{if(!RetainedMessages.get(account).known(key)||!source.isFile()||backup(key)!=null)return;if(!directory.isDirectory()&&!directory.mkdirs())return;File target=new File(directory,key+"_"+source.getName());partial=new File(directory,target.getName()+".part");try(InputStream in=new FileInputStream(source);OutputStream out=new FileOutputStream(partial)){byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1)out.write(b,0,n);}if(!RetainedMessages.get(account).known(key)){partial.delete();return;}if(!partial.renameTo(target)){partial.delete();return;}prefs.edit().putString("backup_"+key,target.getAbsolutePath()).apply();}catch(Exception ignored){if(partial!=null)partial.delete();}});}
 private void restoreOriginal(String key,File saved){String path=prefs.getString("source_"+key,"");if(path.isEmpty()||new File(path).isFile())return;worker.execute(()->{File temp=null;try{if(!RetainedMessages.get(account).known(key))return;File original=new File(path);File parent=original.getParentFile();if(parent!=null&&!parent.isDirectory()&&!parent.mkdirs())return;temp=new File(path+".pakostnik.part");try(InputStream in=new FileInputStream(saved);OutputStream out=new FileOutputStream(temp)){byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1)out.write(b,0,n);}if(!RetainedMessages.get(account).known(key)){temp.delete();return;}if(!temp.renameTo(original)){temp.delete();return;}AndroidUtilities.runOnUIThread(()->NotificationCenter.getInstance(account).postNotificationName(NotificationCenter.updateInterfaces,0,"pakostnik_deleted"));}catch(Exception ignored){if(temp!=null)temp.delete();}});}
 private File backup(String key){String path=prefs.getString("backup_"+key,"");if(path.isEmpty())return null;File f=new File(path);return f.isFile()?f:null;}
 public File retainedPath(TLRPC.Message m){return RetainedMessages.get(account).deleted(m)?backup(RetainedMessages.key(m)):null;}
 public void forget(String key){prefs.edit().remove("source_"+key).apply();worker.execute(()->{String path=prefs.getString("backup_"+key,"");if(!path.isEmpty())new File(path).delete();prefs.edit().remove("backup_"+key).apply();});}
 public void clear(){worker.getQueue().clear();worker.execute(()->{File[] files=directory.listFiles();if(files!=null)for(File f:files)f.delete();prefs.edit().clear().apply();});}
}
