"""Owner-only Telegram controls. Opaque, expiring, single-use callback tokens."""
from __future__ import annotations
import math
from .bot_types import is_sensitive


class Menu:
    def __init__(self, bot):
        self.bot=bot

    def button(self,label,action,**params):
        data=self.bot.store.issue_control(self.bot.config.owner_id,{'action':action,**params},self.bot.clock())
        return {'text':label,'callback_data':data}

    def send(self,text,rows=None):
        params={'chat_id':self.bot.config.owner_id,'text':text}
        if rows is not None:
            params['reply_markup']={'inline_keyboard':rows}
        return self.bot.telegram.call('sendMessage',**params)

    def main(self,extra=''):
        b=self.button
        text=('PAKOSTNIK / УПРАВЛЕНИЕ\n'+('⏸ Автоответы на паузе' if self.bot.store.paused() else '▶️ Автоответы включены')+
              f'\nОбъединение входящих: {self.bot.delay():g} с\nКонтекст: '+('включён' if self.bot.history.enabled() else 'выключен')+
              '\nГолосовые: '+('включены' if self.bot.voice_enabled() else 'выключены'))
        if extra:text+='\n\n'+extra
        return self.send(text,[[b('▶️ Включить','resume'),b('⏸ Пауза','pause')],
                               [b('💬 Чаты','chats'),b('🎭 Мой стиль','style')],
                               [b('🧠 Память','memory'),b('⏳ Задержка','delay')],
                               [b('🎙 Голосовые','voice'),b('ℹ️ Статус','status')]])

    def status(self):
        chats=self.bot.store.list_chats(self.bot.config.owner_id, limit=-1)
        active=sum(1 for c in chats if self.bot.store.connected(c['connection']))
        waiting=sum(1 for c in chats if c['needs_review'])
        return self.main(f'В списке чатов: {len(chats)}; с действующим подключением по последним обновлениям: {active}.\nТребуют ручного внимания: {waiting}.\nОбразцов стиля: {len(self.bot.store.examples())}/8.\nПрава Telegram дополнительно проверяются перед каждой отправкой.')

    def chats(self, page=0):
        rows=[]
        entries=self.bot.store.list_chats(self.bot.config.owner_id, offset=page*15, limit=16)
        for c in entries[:15]:
            mark='❗' if c['needs_review'] else '⏸' if c['stopped'] or c['mode']=='off' or c['paused_until']>self.bot.clock() else '💬'
            rows.append([self.button(mark+' '+(c['title'] or str(c['chat']))[:50],'chat',cid=c['connection'],chat=c['chat'])])
        navigation=[]
        if page:navigation.append(self.button('← Назад','chats',page=page-1))
        if len(entries)>15:navigation.append(self.button('Далее →','chats',page=page+1))
        if navigation:rows.append(navigation)
        rows.append([self.button('К меню','main')])
        return self.send('Разрешённые Business-чаты, полученные этим сервисом.\nВыбери переписку для режима и стиля.' if len(rows)>1 else 'Чатов пока нет. Подключи бота в Telegram Business и получи новое сообщение.',rows)

    def chat(self,cid,chat):
        if self.bot.store.owner(cid)!=self.bot.config.owner_id:
            return self.main('Это подключение недоступно.')
        c=self.bot.store.chat(cid,chat);b=self.button
        mode={'auto':'Автопилот','assist':'Помощник — с подтверждением','off':'Ручной'}[c['mode']]
        text=f"{c['title'] or chat}\nРежим: {mode}"
        if c['needs_review']:text+='\n❗ Нужен ручной ответ: '+c['reason']
        if c['stopped']:text+='\n⏸ Собеседник остановил ИИ командой /stop.'
        elif c['paused_until']>self.bot.clock():text+=f"\n⏸ Пауза после ручного ответа: ещё {math.ceil((c['paused_until']-self.bot.clock())/60)} мин."
        if not self.bot.store.connected(cid):text+='\nBusiness-подключение сейчас не даёт права ответа.'
        text+='\nСтиль: '+(c['style'] or 'общий профиль')
        p={'cid':cid,'chat':chat}
        return self.send(text,[[b('Автопилот','mode',value='auto',**p),b('Помощник','mode',value='assist',**p)],
                               [b('Ручной','mode',value='off',**p),b('Возобновить чат','resume_chat',**p)],
                               [b('Стиль чата','ask_chat_style',**p),b('Очистить память','confirm_clear',**p)],
                               [b('К списку чатов','chats')]])

    def style(self):
        return self.send('Манера общения:\n'+self.bot.store.get('style',self.bot.config.style)+
                         f'\n\nОбразцов: {len(self.bot.store.examples())}/8. Пример можно добавить командой:\n/example как дела? => да норм, ты как',
                         [[self.button('Изменить стиль','ask_style'),self.button('Образцы','examples')],
                          [self.button('Сбросить профиль','confirm_style_reset'),self.button('К меню','main')]])

    def memory(self):
        return self.send(f'Короткий контекст: до {self.bot.config.context_max_messages} сообщений и {self.bot.config.context_max_chars} символов на чат; срок до {self.bot.config.context_ttl_seconds//3600} ч.\nГлобальный предел — 500 сообщений. Он хранится на твоём устройстве/сервере и передаётся провайдеру вместе с новым сообщением. Полная история Telegram не загружается. Выключение удаляет накопленный короткий контекст.',
                         [[self.button('Выключить память' if self.bot.history.enabled() else 'Включить память','memory_toggle')],
                          [self.button('Очистить всю память','confirm_clear_all'),self.button('К меню','main')]])

    def delay(self):
        return self.send(f'Текущая пауза: {self.bot.delay():g} с. Новые сообщения продлевают окно до заданного предела, после чего готовится общий ответ.',
                         [[self.button(str(n)+' с','set_delay',value=n) for n in (0,3,6)],
                          [self.button(str(n)+' с','set_delay',value=n) for n in (10,15)],
                          [self.button('К меню','main')]])

    def voice(self):
        return self.send('Голосовые и кружки: '+('включены' if self.bot.voice_enabled() else 'выключены')+
                         f'\nПри включении новые записи до {self.bot.config.voice_max_seconds} с и {self.bot.config.voice_max_bytes//(1024*1024)} МБ передаются провайдеру распознавания. Это отдельные API-запросы. После расшифровки ИИ отвечает текстом. Содержимое записи до распознавания неизвестно; в ней тоже могут быть личные данные.',
                         [[self.button('Выключить' if self.bot.voice_enabled() else 'Включить распознавание','voice_toggle')],
                          [self.button('К меню','main')]])

    def ask(self,payload,text):
        result=self.bot.telegram.call('sendMessage',chat_id=self.bot.config.owner_id,text=text,
             reply_markup={'force_reply':True,'selective':True,'input_field_placeholder':'Ответь на это сообщение'})
        if isinstance(result,dict) and isinstance(result.get('message_id'),int):
            self.bot.store.prompt(result['message_id'],payload,self.bot.clock())

    def draft(self,token):
        d=self.bot.drafts.get(token,self.bot.clock())
        if not d or not self.bot.current(d['connection'],d['chat'],d['mid'],d['generation'],d['source_date']):
            return self.main('Предложение устарело. Нужен свежий ответ на актуальное сообщение.')
        if d['state']!='pending':
            return self.main('Это предложение уже обработано.')
        c=self.bot.store.chat(d['connection'],d['chat']);p={'draft':token,'revision':d['revision']};b=self.button
        rows=[[b('Отправить','send_draft',**p),b('Исправить','edit_draft',**p)],
              [b('Отклонить','dismiss_draft',**p),b('Открыть настройки чата','chat',cid=d['connection'],chat=d['chat'])]]
        if d['edited'] and len(d['source'])<=500 and len(d['body'])<=500:
            rows.insert(1,[b('Отправить и запомнить мой вариант','send_teach',**p)])
        return self.send(f"Предложение для {c['title'] or d['chat']}\n\nВходящее: {d['source'][:500]}\n\nОтвет:\n{d['body']}",rows)

    def callback(self,query):
        owner=self.bot.config.owner_id
        message=query.get('message',{});chat=message.get('chat',{})
        if not owner or query.get('from',{}).get('id')!=owner or chat.get('id')!=owner or chat.get('type')!='private':
            self.bot.telegram.call('answerCallbackQuery',callback_query_id=query['id'],text='Недоступно')
            return
        data=query.get('data','')
        payload=self.bot.store.take_control(owner,data[2:],self.bot.clock()) if isinstance(data,str) and data.startswith('p:') else None
        self.bot.telegram.call('answerCallbackQuery',callback_query_id=query['id'],text='Готово' if payload else 'Кнопка устарела. Открой /menu заново.')
        if not payload:return
        action=payload['action'];cid=payload.get('cid');peer=payload.get('chat');b=self.button
        if cid is not None and self.bot.store.owner(cid)!=owner:
            return self.main('Это подключение недоступно.')
        if action=='main':return self.main()
        if action=='status':return self.status()
        if action=='chats':return self.chats(payload.get('page',0))
        if action=='chat':return self.chat(cid,peer)
        if action=='style':return self.style()
        if action=='examples':return self.bot.show_examples()
        if action=='memory':return self.memory()
        if action=='delay':return self.delay()
        if action=='voice':return self.voice()
        if action in ('pause','resume'):
            self.bot.set_paused(action=='pause');return self.main()
        if action=='mode':
            self.bot.store.mode(cid,peer,payload['value']);self.bot.cancel(cid,peer)
            if payload['value']=='off':self.bot.history.clear(cid,peer);self.bot.drafts.clear(cid,peer)
            return self.chat(cid,peer)
        if action=='resume_chat':
            self.bot.store.resume_chat(peer);self.bot.cancel(cid,peer);return self.chat(cid,peer)
        if action=='ask_style':return self.ask({'action':'style'},'Напиши, как тебе обычно свойственно отвечать: коротко/подробно, юмор, эмодзи, обращение. До 500 символов, без секретов.')
        if action=='ask_chat_style':return self.ask({'action':'chat_style','cid':cid,'chat':peer},'Стиль только для этой переписки, до 500 символов. Напиши «общий», чтобы использовать общий профиль.')
        if action=='set_delay':
            self.bot.set_delay(payload['value']);return self.delay()
        if action=='memory_toggle':
            enabled=not self.bot.history.enabled();self.bot.clear_context();self.bot.history.configure(enabled);return self.memory()
        if action=='voice_toggle':
            self.bot.store.invalidate();self.bot.cancel_all();self.bot.store.set('voice_enabled','0' if self.bot.voice_enabled() else '1');return self.voice()
        if action in ('confirm_clear','confirm_clear_all'):
            return self.send('Удалить короткий контекст '+('этой переписки?' if cid else 'всех переписок?'),
                             [[b('Очистить','clear_context',**({'cid':cid,'chat':peer} if cid else {})),b('Отмена','main')]])
        if action=='clear_context':
            self.bot.clear_context(cid,peer);return self.main('Короткий контекст очищен. Образцы твоей манеры общения сохранены.')
        if action=='confirm_style_reset':
            return self.send('Удалить образцы и сбросить профиль общения?',[[b('Сбросить','reset_style'),b('Отмена','style')]])
        if action=='reset_style':
            self.bot.reset_style();return self.style()
        if action in ('send_draft','send_teach'):
            return self.bot.approve(payload['draft'],payload['revision'],teach=action=='send_teach')
        if action=='dismiss_draft':
            done=self.bot.drafts.dismiss(payload['draft'],payload['revision'],self.bot.clock());return self.main('Предложение отклонено, собеседнику ничего не отправлено.' if done else 'Это предложение уже изменилось или обработано.')
        if action=='edit_draft':
            d=self.bot.drafts.get(payload['draft'],self.bot.clock())
            if not d or d['revision']!=payload['revision'] or d['state']!='pending' or not self.bot.current(d['connection'],d['chat'],d['mid'],d['generation'],d['source_date']):
                return self.main('Предложение устарело.')
            return self.ask({'action':'draft_edit',**{k:payload[k] for k in ('draft','revision')}},'Напиши свой вариант ответа, до 1500 символов. Он сначала появится в предложении, автоматически не отправится.')

    def owner_input(self,message):
        reply=message.get('reply_to_message',{})
        if not reply:return False
        payload=self.bot.store.take_prompt(reply.get('message_id'),self.bot.clock())
        if not payload:return False
        text=message.get('text','').strip();action=payload['action']
        if not text or is_sensitive(text):
            self.main('Текст пустой или похож на чувствительные данные. Такой ответ лучше отправить вручную в Telegram.')
            return True
        if action in ('style','chat_style'):
            if len(text)>500:self.main('До 500 символов для стиля.');return True
            if action=='style':self.bot.set_style(text)
            else:
                cid,chat=payload['cid'],payload['chat']
                if self.bot.store.owner(cid)!=self.bot.config.owner_id:return True
                self.bot.store.chat_style(cid,chat,'' if text.lower()=='общий' else text);self.bot.cancel(cid,chat)
            self.main('Стиль сохранён.');return True
        if action=='draft_edit':
            d=self.bot.drafts.get(payload['draft'],self.bot.clock())
            if not d or len(text)>1500 or not self.bot.current(d['connection'],d['chat'],d['mid'],d['generation'],d['source_date']):
                self.main('Предложение устарело или ответ слишком длинный.');return True
            if self.bot.drafts.revise(payload['draft'],text,payload['revision'],self.bot.clock()):self.draft(payload['draft'])
            else:self.main('Предложение уже изменилось.')
            return True
        return True
