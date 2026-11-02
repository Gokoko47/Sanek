package org.telegram.ui;

import android.content.Context;
import android.graphics.Color;
import android.text.InputType;
import android.view.View;
import android.widget.*;
import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.MessagesController;
import org.telegram.tgnet.TLRPC;
import java.util.ArrayList;
import org.telegram.messenger.pakostnik.*;
import org.telegram.messenger.MessageObject;
import android.graphics.Typeface;
import org.telegram.ui.ActionBar.*;

public class PakostnikSettingsActivity extends BaseFragment {
 private final long dialog;
 private TextView status;
 public PakostnikSettingsActivity(int account,long dialog){super();currentAccount=account;this.dialog=dialog;}
 private int dp(float x){return AndroidUtilities.dp(x);}
 private TextView label(Context c,LinearLayout box,String text){TextView t=new TextView(c);t.setText(text);t.setTextColor(Color.WHITE);t.setTextSize(15);t.setTypeface(PakostnikAppearance.typeface());t.setPadding(0,dp(12),0,dp(8));box.addView(t);return t;}
 private Button button(Context c,LinearLayout box,String text,Runnable action){Button b=new Button(c);b.setText(text);b.setTypeface(PakostnikAppearance.typeface());b.setTextColor(PakostnikAppearance.accent());b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(PakostnikAppearance.surface()));box.addView(b,new LinearLayout.LayoutParams(-1,-2));b.setOnClickListener(v->{action.run();refresh();});return b;}
 private EditText input(Context c,LinearLayout box,String hint,String value,boolean secret){EditText e=new EditText(c);e.setTypeface(PakostnikAppearance.typeface());e.setTextColor(Color.WHITE);e.setHintTextColor(0xffaaaaaa);e.setBackgroundTintList(android.content.res.ColorStateList.valueOf(PakostnikAppearance.accent()));e.setHint(hint);e.setSingleLine(true);e.setInputType(secret?InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD:InputType.TYPE_CLASS_TEXT);e.setText(value);box.addView(e,new LinearLayout.LayoutParams(-1,-2));return e;}
 private void refresh(){PakostnikAI a=PakostnikAI.get(currentAccount);status.setText((a.enabled()?"ИИ включён":"ИИ выключен")+(dialog==0?"\nОбщие настройки":"\nРежим чата: "+new String[]{"Ручной","Помощник","Автопилот"}[a.mode(dialog)])+"\n"+a.status());}
 private void pickChat(Context context){
  PakostnikAI a=PakostnikAI.get(currentAccount);
  ArrayList<Long> ids=new ArrayList<>();ArrayList<String> names=new ArrayList<>();
  MessagesController controller=MessagesController.getInstance(currentAccount);
  for(TLRPC.Dialog d:controller.getAllDialogs()){
   if(!a.eligible(d.id))continue;
   TLRPC.User u=controller.getUser(d.id);
   String name=((u.first_name==null?"":u.first_name)+" "+(u.last_name==null?"":u.last_name)).trim();
   ids.add(d.id);names.add((name.isEmpty()?Long.toString(d.id):name)+" — "+new String[]{"Ручной","Помощник","Автопилот"}[a.mode(d.id)]);
  }
  if(ids.isEmpty()){Toast.makeText(context,"Нет доступных личных чатов. Сначала откройте переписку в списке чатов.",Toast.LENGTH_LONG).show();return;}
  new android.app.AlertDialog.Builder(context).setTitle("Выберите чат").setItems(names.toArray(new String[0]),(d,index)->presentFragment(new PakostnikSettingsActivity(currentAccount,ids.get(index)))).setNegativeButton("Отмена",null).show();
 }
 private void pickVoice(Context context){
  ArrayList<MessageObject> messages=VoiceTranscriber.messages(currentAccount);
  if(messages.isEmpty()){Toast.makeText(context,"Голосовых или кружков пока нет. Откройте переписку с записью.",Toast.LENGTH_LONG).show();return;}
  String[] names=new String[messages.size()];for(int i=0;i<names.length;i++){MessageObject m=messages.get(i);names[i]=(m.isRoundVideo()?"Кружок":"Голосовое")+" · чат "+m.getDialogId()+" · "+new java.util.Date(m.messageOwner.date*1000L);}
  new android.app.AlertDialog.Builder(context).setTitle("Расшифровать запись").setItems(names,(d,index)->{
   MessageObject m=messages.get(index);
   new AlertDialog.Builder(context).setTitle("Расшифровка").setMessage("Передать эту запись вашему серверу и ИИ-провайдеру для распознавания речи? Результат будет показан только вам.").setPositiveButton("Расшифровать",(a,w)->{Toast.makeText(context,"Распознавание речи…",Toast.LENGTH_LONG).show();VoiceTranscriber.transcribe(currentAccount,m,text->{if(!isFinished)presentFragment(new PakostnikTextActivity(currentAccount,"Расшифровка",text));});}).setNegativeButton("Отмена",null).show();
  }).setNegativeButton("Отмена",null).show();
 }
 @Override public View createView(Context context){
  actionBar.setTitle("Pakostnik AI");actionBar.setBackButtonImage(org.telegram.messenger.R.drawable.ic_ab_back);
  actionBar.setActionBarMenuOnItemClick(new ActionBar.ActionBarMenuOnItemClick(){@Override public void onItemClick(int id){if(id==-1)finishFragment();}});
  ScrollView scroll=new ScrollView(context);scroll.setBackgroundColor(PakostnikAppearance.background());LinearLayout box=new LinearLayout(context);box.setOrientation(LinearLayout.VERTICAL);box.setPadding(dp(20),dp(12),dp(20),dp(24));scroll.addView(box);
  PakostnikAI a=PakostnikAI.get(currentAccount);
  label(context,box,"PAKOSTNIK // CONTROL").setTextColor(PakostnikAppearance.accent());
  button(context,box,"Оформление / Console",()->presentFragment(new PakostnikAppearanceActivity(currentAccount)));
  status=label(context,box,"");refresh();
  label(context,box,"Неофициальный клиент Telegram. ИИ получает только новые текстовые сообщения выбранного личного чата после включения режима владельцем аккаунта. История и медиа не передаются. Собеседник может остановить ИИ командой /stop. После перезапуска нужно заново включить ИИ и выбрать режим чата.");
  EditText endpoint=input(context,box,"HTTPS URL сервера, включая /reply",a.setting("endpoint"),false);
  EditText token=input(context,box,"Токен доступа к вашему серверу",a.setting("token"),true);
  EditText style=input(context,box,"Стиль: кратко, дружелюбно, с юмором",a.setting("style"),false);
  button(context,box,"Сохранить подключение и стиль",()->{try{a.configure(endpoint.getText().toString().trim(),token.getText().toString().trim(),style.getText().toString().trim());Toast.makeText(context,"Сохранено. ИИ остановлен; включите заново.",Toast.LENGTH_LONG).show();}catch(Exception e){Toast.makeText(context,"Нужны HTTPS URL, токен от 32 символов и стиль до 300 символов",Toast.LENGTH_LONG).show();}});
  button(context,box,"Включить ИИ для этого аккаунта",()->new AlertDialog.Builder(context).setTitle("Разрешить обработку сообщений ИИ?").setMessage("Сообщения разрешённых чатов будут передаваться вашему серверу и его ИИ-провайдеру. Убедитесь, что знакомы с их политикой обработки данных. Автопилот может ошибаться. Важные вопросы требуют ручного ответа.").setPositiveButton("Разрешить",(d,w)->{a.enable(true);refresh();}).setNegativeButton("Отмена",null).show());
  button(context,box,"ОСТАНОВИТЬ ИИ ВО ВСЕХ АККАУНТАХ",a::stopAll);
  label(context,box,"МЕДИА // УДАЛЁННЫЕ СООБЩЕНИЯ").setTextColor(PakostnikAppearance.accent());
  button(context,box,"Расшифровать голосовое или кружок",()->pickVoice(context));
  RetainedMessages retained=RetainedMessages.get(currentAccount);
  Switch keep=new Switch(context);keep.setText("Оставлять удалённые сообщения в чате ✕");keep.setTextColor(Color.WHITE);keep.setTypeface(PakostnikAppearance.typeface());PakostnikAppearance.tint(keep);keep.setChecked(retained.enabled());box.addView(keep);keep.setOnCheckedChangeListener((b,value)->retained.enabled(value));
  label(context,box,"Включено по умолчанию: входящие сообщения остаются с пометкой ✕ удалено. Скачанные медиа дополнительно копируются в хранилище приложения. Секретные, защищённые и исчезающие сообщения исключены. Удаление вами и очистка истории работают штатно.");
  RetainedMedia media=RetainedMedia.get(currentAccount);
  Switch download=new Switch(context);download.setText("Автоскачивание новых медиа для сохранения");download.setTextColor(Color.WHITE);download.setTypeface(PakostnikAppearance.typeface());PakostnikAppearance.tint(download);download.setChecked(media.downloadEnabled());box.addView(download);download.setOnCheckedChangeListener((b,value)->media.downloadEnabled(value));
  LocalArchive archive=LocalArchive.get(currentAccount);
  Switch cache=new Switch(context);cache.setText("Дополнительный текстовый архив (7 дней)");cache.setTextColor(Color.WHITE);cache.setTypeface(PakostnikAppearance.typeface());PakostnikAppearance.tint(cache);cache.setChecked(archive.enabled());box.addView(cache);cache.setOnCheckedChangeListener((b,value)->archive.enabled(value));
  button(context,box,"Посмотреть удалённые сообщения",()->archive.readDeleted(dialog,text->{if(!isFinished)presentFragment(new PakostnikTextActivity(currentAccount,"Локальный архив",text));}));
  button(context,box,"Очистить локальный архив",()->new AlertDialog.Builder(context).setTitle("Очистить архив?").setMessage("Локальные копии текста будут удалены с этого устройства.").setPositiveButton("Очистить",(d,w)->archive.clear()).setNegativeButton("Отмена",null).show());
  label(context,box,"Архив: до 500 входящих текстовых сообщений за 7 дней. Секретные чаты, защищённые и исчезающие сообщения не сохраняются. Удалённый текст появится только если клиент успел получить его до удаления. Запись голосовых и кружков — штатными кнопками в переписке.");
  button(context,box,"Выбрать чат для настройки",()->pickChat(context));
  if(dialog!=0){
  label(context,box,"Режим этой переписки. Помощник и автопилот начинают работать сразу после выбора. Собеседнику отправляется уведомление об ИИ; подтверждать его не нужно.");
  button(context,box,"Ручной",()->a.choose(dialog,0));
  button(context,box,"Помощник — предложить ответ",()->a.choose(dialog,1));
  button(context,box,"Автопилот — отвечать самостоятельно",()->a.choose(dialog,2));
  button(context,box,"Обновить статус",()->{});
  button(context,box,"Показать предложенный ответ",()->{String draft=a.draft(dialog);if(draft==null){Toast.makeText(context,"Свежего предложения пока нет",Toast.LENGTH_SHORT).show();return;}new AlertDialog.Builder(context).setTitle("Проверка ответа").setMessage(draft).setPositiveButton("Отправить",(d,w)->{a.approve(dialog);refresh();}).setNegativeButton("Отмена",null).show();});
  }
  label(context,box,"Ограничения первой версии: до 10 автоответов в час на аккаунт и один в минуту в чате. Поддерживается текст, без анализа полной истории. Фоновая работа зависит от Android и доставки обновлений Telegram. После принудительной остановки приложение не отвечает.");
  fragmentView=scroll;return fragmentView;
 }
}
