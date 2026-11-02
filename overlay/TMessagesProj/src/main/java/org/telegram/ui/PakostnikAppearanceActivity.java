package org.telegram.ui;

import android.content.Context;
import android.graphics.Typeface;
import android.view.View;
import android.widget.*;
import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.pakostnik.*;
import org.telegram.ui.ActionBar.*;

/** Dedicated customization screen with a local preview and explicit Apply. */
public final class PakostnikAppearanceActivity extends BaseFragment {
 private EditText background,accent;
 private Switch mono;
 private SeekBar size,radius;
 private TextView sample,sizeLabel,radiusLabel;
 private LinearLayout preview;
 public PakostnikAppearanceActivity(int account){currentAccount=account;}
 private TextView label(Context c,LinearLayout parent,String s){TextView t=new TextView(c);t.setText(s);t.setTextColor(0xffeeeeee);t.setTypeface(PakostnikAppearance.typeface());t.setTextSize(15);t.setPadding(0,AndroidUtilities.dp(12),0,AndroidUtilities.dp(8));parent.addView(t);return t;}
 private EditText color(Context c,LinearLayout parent,String title,int value){label(c,parent,title);EditText e=new EditText(c);e.setText(ConsolePalette.hex(value));e.setTextColor(0xffeeeeee);e.setSingleLine(true);e.setBackgroundTintList(android.content.res.ColorStateList.valueOf(PakostnikAppearance.accent()));e.setTypeface(Typeface.MONOSPACE);parent.addView(e);return e;}
 private Button button(Context c,LinearLayout parent,String title,Runnable action){Button b=new Button(c);b.setText(title);b.setTypeface(PakostnikAppearance.typeface());b.setTextColor(PakostnikAppearance.accent());b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(PakostnikAppearance.surface()));parent.addView(b);b.setOnClickListener(v->action.run());return b;}
 private void update(){int bg,a;try{bg=ConsolePalette.parse(background.getText().toString());a=ConsolePalette.parse(accent.getText().toString());ConsolePalette.validate(bg,a);}catch(Exception e){bg=0xff000000;a=0xffeeeeee;}preview.setBackgroundColor(bg);sample.setTextColor(a);sample.setTextSize(12+size.getProgress());sample.setTypeface(mono.isChecked()?Typeface.MONOSPACE:Typeface.DEFAULT);android.graphics.drawable.GradientDrawable bubble=new android.graphics.drawable.GradientDrawable();bubble.setColor(ConsolePalette.surface(bg,.065));bubble.setCornerRadius(AndroidUtilities.dp(radius.getProgress()));sample.setBackground(bubble);sizeLabel.setText("Текст сообщений: "+(12+size.getProgress())+" sp");radiusLabel.setText("Скругление сообщений: "+radius.getProgress()+" dp");}
 private void preset(int bg,int a,boolean terminal,int curve){background.setText(ConsolePalette.hex(bg));accent.setText(ConsolePalette.hex(a));mono.setChecked(terminal);radius.setProgress(curve);update();}
 @Override public View createView(Context c){
  actionBar.setTitle("Оформление / Console");actionBar.setBackButtonImage(org.telegram.messenger.R.drawable.ic_ab_back);actionBar.setActionBarMenuOnItemClick(new ActionBar.ActionBarMenuOnItemClick(){@Override public void onItemClick(int id){if(id==-1)finishFragment();}});
  ScrollView scroll=new ScrollView(c);scroll.setBackgroundColor(PakostnikAppearance.background());LinearLayout box=new LinearLayout(c);box.setOrientation(LinearLayout.VERTICAL);int p=AndroidUtilities.dp(20);box.setPadding(p,p,p,p);scroll.addView(box);
  label(c,box,"PAKOSTNIK / APPEARANCE");
  background=color(c,box,"Фон: #RRGGBB",PakostnikAppearance.background());accent=color(c,box,"Акцент: #RRGGBB",PakostnikAppearance.accent());
  mono=new Switch(c);mono.setText("Моноширинный шрифт");mono.setTextColor(0xffeeeeee);mono.setChecked(PakostnikAppearance.mono());PakostnikAppearance.tint(mono);box.addView(mono);
  sizeLabel=label(c,box,"");size=new SeekBar(c);size.setMax(12);size.setProgressTintList(android.content.res.ColorStateList.valueOf(PakostnikAppearance.accent()));size.setThumbTintList(android.content.res.ColorStateList.valueOf(PakostnikAppearance.accent()));size.setProgress(PakostnikAppearance.size()-12);box.addView(size);
  radiusLabel=label(c,box,"");radius=new SeekBar(c);radius.setMax(18);radius.setProgressTintList(android.content.res.ColorStateList.valueOf(PakostnikAppearance.accent()));radius.setThumbTintList(android.content.res.ColorStateList.valueOf(PakostnikAppearance.accent()));radius.setProgress(PakostnikAppearance.radius());box.addView(radius);
  preview=new LinearLayout(c);preview.setPadding(p,p,p,p);sample=new TextView(c);sample.setPadding(p/2,p/2,p/2,p/2);sample.setText("> Алексей / в сети\n\n[14:20] Привет!\n[14:21] Встречаемся в семь?\n         ✕ удалено\n\n> Сообщение_");preview.addView(sample);box.addView(preview);update();
  SeekBar.OnSeekBarChangeListener changes=new SeekBar.OnSeekBarChangeListener(){public void onProgressChanged(SeekBar b,int v,boolean user){update();}public void onStartTrackingTouch(SeekBar b){}public void onStopTrackingTouch(SeekBar b){}};size.setOnSeekBarChangeListener(changes);radius.setOnSeekBarChangeListener(changes);mono.setOnCheckedChangeListener((b,value)->update());
  android.text.TextWatcher colors=new android.text.TextWatcher(){public void beforeTextChanged(CharSequence s,int start,int count,int after){}public void onTextChanged(CharSequence s,int start,int before,int count){update();}public void afterTextChanged(android.text.Editable e){}};background.addTextChangedListener(colors);accent.addTextChangedListener(colors);
  button(c,box,"Чёрно-белая консоль",()->preset(0xff000000,0xfff2f2f2,true,0));
  button(c,box,"Графит",()->preset(0xff101010,0xffeeeeee,true,4));
  button(c,box,"Зелёный терминал",()->preset(0xff000000,0xffa6ff80,true,0));
  button(c,box,"Применить оформление",()->{try{PakostnikAppearance.save(ConsolePalette.parse(background.getText().toString()),ConsolePalette.parse(accent.getText().toString()),mono.isChecked(),12+size.getProgress(),radius.getProgress());Toast.makeText(c,"Оформление сохранено",Toast.LENGTH_SHORT).show();}catch(Exception e){Toast.makeText(c,"Укажите тёмный фон и контрастный акцент в формате #RRGGBB",Toast.LENGTH_LONG).show();}});
  label(c,box,"Настройки общие для аккаунтов. Меняется оформление: основные возможности Telegram остаются доступны. Для других тем, обоев и стандартных настроек используйте обычный раздел оформления Telegram.");
  fragmentView=scroll;return scroll;
 }
}
