package org.telegram.messenger.pakostnik;

import android.content.SharedPreferences;
import android.graphics.Typeface;
import android.util.SparseIntArray;
import org.telegram.messenger.*;
import org.telegram.ui.ActionBar.*;

/** Global look preferences. Telegram transport and account settings are untouched. */
public final class PakostnikAppearance {
 private PakostnikAppearance(){}
 private static SharedPreferences prefs(){return ApplicationLoader.applicationContext.getSharedPreferences("pakostnik_appearance",0);}
 public static int background(){return prefs().getInt("background",0xff000000);}
 public static int accent(){return prefs().getInt("accent",0xfff2f2f2);}
 public static int surface(){return ConsolePalette.surface(background(),.065);}
 public static boolean mono(){return prefs().getBoolean("mono",true);}
 public static Typeface typeface(){return mono()?Typeface.MONOSPACE:Typeface.DEFAULT;}
 public static void tint(android.widget.Switch control){int[][] states={new int[]{android.R.attr.state_checked},new int[]{}};control.setThumbTintList(new android.content.res.ColorStateList(states,new int[]{accent(),0xff777777}));control.setTrackTintList(new android.content.res.ColorStateList(states,new int[]{(accent()&0xffffff)|0x66000000,0xff333333}));}
 public static int size(){return Math.max(12,Math.min(24,SharedConfig.fontSize));}
 public static int radius(){return Math.max(0,Math.min(18,SharedConfig.bubbleRadius));}
 public static void save(int bg,int accent,boolean mono,int size,int radius){
  ConsolePalette.validate(bg,accent);if(size<12||size>24||radius<0||radius>18)throw new IllegalArgumentException();
  prefs().edit().putInt("background",bg).putInt("accent",accent).putBoolean("mono",mono).apply();
  SharedConfig.fontSize=size;SharedConfig.fontSizeIsDefault=false;SharedConfig.bubbleRadius=radius;
  MessagesController.getGlobalMainSettings().edit().putInt("fons_size",size).putInt("bubbleRadius",radius).putString("theme","Pakostnik").putString("nighttheme","Pakostnik").apply();
  Theme.createCommonMessageResources();
  Theme.reloadAllResources(ApplicationLoader.applicationContext);
  NotificationCenter.getGlobalInstance().postNotificationName(NotificationCenter.needSetDayNightTheme,Theme.getTheme("Pakostnik"),false,null,-1);
 }
 private static void put(SparseIntArray map,int color,String...names){for(String name:names){int key=ThemeColors.stringKeyToInt(name);if(key>=0)map.put(key,color);}}
 public static void customize(SparseIntArray map){
  // Keep wallpaper offsets and other non-color metadata intact.
  for(int i=0;i<map.size();i++)if(map.keyAt(i)!=Theme.key_wallpaperFileOffset)map.setValueAt(i,ConsolePalette.gray(map.valueAt(i)));
  int bg=background(),a=accent(),surface=surface(),out=ConsolePalette.surface(bg,.11);
  put(map,bg,"windowBackgroundGray","chat_wallpaper","actionBarDefault","actionBarDefaultArchived");
  put(map,surface,"windowBackgroundWhite","dialogBackground","chat_inBubble","chat_messagePanelBackground","chat_attachPermissionImage","chats_menuBackground");
  put(map,out,"chat_outBubble","chat_outBubbleGradient1","chat_outBubbleGradient2","chat_outBubbleGradient3","chat_outBubbleSelected","chat_inBubbleSelected");
  put(map,0xffeeeeee,"windowBackgroundWhiteBlackText","dialogTextBlack","actionBarDefaultTitle","actionBarDefaultIcon","chats_name","chat_messageTextIn","chat_messageTextOut","chat_messagePanelText","profile_title");
  put(map,0xffaaaaaa,"chats_message","chats_date","chat_inTimeText","chat_outTimeText","actionBarDefaultSubtitle");
  put(map,a,"windowBackgroundWhiteBlueText","windowBackgroundWhiteBlueText2","dialogTextBlue","dialogButton","chat_messagePanelSend","chat_outSentCheck","chat_outSentCheckSelected","chat_inAudioSeekbar","chat_outAudioSeekbar","chat_inAudioSelectedProgress","chat_outAudioSelectedProgress","chat_inVoiceSeekbar","chat_outVoiceSeekbar","chat_outAudioSelectedProgress","chat_inAudioProgress","chat_outAudioProgress","switchTrackChecked","radioBackgroundChecked","checkbox","chats_unreadCounter","chats_actionBackground","avatar_backgroundRed","avatar_backgroundOrange","avatar_backgroundViolet","avatar_backgroundGreen","avatar_backgroundCyan","avatar_backgroundBlue","avatar_backgroundPink");
  int onAccent=ConsolePalette.contrast(a,0xff000000)>=ConsolePalette.contrast(a,0xffffffff)?0xff000000:0xffffffff;
  put(map,onAccent,"chats_unreadCounterText","chats_actionIcon","checkboxCheck","avatar_text");
 }
}
