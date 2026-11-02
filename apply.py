#!/usr/bin/env python3
"""Apply the Pakostnik overlay to the exact upstream revision; fails on drift."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
BASE='3de37c8cfb039452be7398909461da6288babf15'
root=Path(sys.argv[1] if len(sys.argv)>1 else 'Telegram').resolve()
here=Path(__file__).resolve().parent
if subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()!=BASE:
    raise SystemExit('Unexpected Telegram revision. See UPSTREAM.txt')
marker=root/'.pakostnik-applied'
if marker.exists():
    raise SystemExit('Already applied. Use a clean checkout.')
def edit(path,old,new,count=1):
    f=root/path
    s=f.read_text()
    if s.count(old)!=count:
        raise SystemExit(f'Patch mismatch: {path}: expected {count}, found {s.count(old)}')
    f.write_text(s.replace(old,new))
java='TMessagesProj/src/main/java/org/telegram/'
edit(java+'messenger/MessagesController.java',
     '    public boolean updateInterfaceWithMessages(long dialogId, ArrayList<MessageObject> messages, int mode) {',
     '    public boolean updateInterfaceWithMessages(long dialogId, ArrayList<MessageObject> messages, int mode) {\n        org.telegram.messenger.pakostnik.PakostnikAI.get(currentAccount).onMessages(messages, mode == ChatActivity.MODE_SCHEDULED, mode);')
edit(java+'messenger/MessagesController.java','    public void cleanup() {','    public void cleanup() {\n        org.telegram.messenger.pakostnik.PakostnikAI.get(currentAccount).logout();')
edit(java+'messenger/SendMessagesHelper.java','    public void sendMessage(SendMessageParams sendMessageParams) {',
     '    public void sendMessage(SendMessageParams sendMessageParams) {\n        org.telegram.messenger.pakostnik.PakostnikAI.get(currentAccount).manualSend(sendMessageParams.peer);')
edit(java+'ui/DialogsActivity.java',
     '        io.add(R.drawable.outline_groups_24, getString(R.string.NewGroup), () -> {',
     '        io.add(R.drawable.msg_settings_old, "Pakostnik AI", () -> presentFragment(new PakostnikSettingsActivity(currentAccount, 0)));\n        io.add(R.drawable.outline_groups_24, getString(R.string.NewGroup), () -> {')
edit(java+'messenger/MessagesController.java',
     '                    getNotificationCenter().postNotificationName(NotificationCenter.messagesDeleted, arrayList, -dialogId, false);',
     '                    if (dialogId == 0) { org.telegram.messenger.pakostnik.LocalArchive.get(currentAccount).deleted(arrayList); org.telegram.messenger.pakostnik.PakostnikAI.get(currentAccount).onDeleted(arrayList); }\n                    getNotificationCenter().postNotificationName(NotificationCenter.messagesDeleted, arrayList, -dialogId, false);')
edit(java+'ui/ActionBar/Theme.java',
     '        String themesString = themeConfig.getString("themes2", null);',
     '        ThemeInfo pakostnikTheme = new ThemeInfo();\n        pakostnikTheme.name = "Pakostnik";\n        pakostnikTheme.assetName = "pakostnik.attheme";\n        pakostnikTheme.previewBackgroundColor = 0xff080808;\n        pakostnikTheme.previewInColor = 0xff161616;\n        pakostnikTheme.previewOutColor = 0xff301214;\n        pakostnikTheme.sortIndex = 5;\n        themes.add(pakostnikTheme);\n        themesDict.put("Pakostnik", pakostnikTheme);\n        String themesString = themeConfig.getString("themes2", null);')
edit(java+'ui/ActionBar/Theme.java','String theme = preferences.getString("theme", null);','String theme = preferences.getString("theme", "Pakostnik");')
edit(java+'ui/ActionBar/Theme.java','theme = preferences.getString("nighttheme", null);','theme = preferences.getString("nighttheme", "Pakostnik");')
edit(java+'ui/ActionBar/Theme.java',
     '                chat_msgTextPaint = new TextPaint(Paint.ANTI_ALIAS_FLAG);',
     '                chat_msgTextPaint = new TextPaint(Paint.ANTI_ALIAS_FLAG);\n                chat_msgTextPaint.setTypeface(android.graphics.Typeface.MONOSPACE);')

edit(java+'ui/ChatActivity.java',
     '        ArrayList<MessageObject> messArr = (ArrayList<MessageObject>) args[2];',
     '        ArrayList<MessageObject> messArr = (ArrayList<MessageObject>) args[2];\n        for (MessageObject cached : messArr) { org.telegram.messenger.pakostnik.RetainedMessages.get(currentAccount).remember(cached); org.telegram.messenger.pakostnik.LocalArchive.get(currentAccount).record(cached); org.telegram.messenger.pakostnik.VoiceTranscriber.remember(currentAccount, cached); }')
f=root/(java+'ui/ChatActivity.java')
s=f.read_text()
anchor='        actionBar.setActionBarMenuOnItemClick(new ActionBar.ActionBarMenuOnItemClick() {\n            @Override\n            public void onItemClick(final int id) {'
assert s.count(anchor)==1
s=s.replace(anchor,anchor+'\n                if (id == 990702) { org.telegram.messenger.pakostnik.LocalArchive.get(currentAccount).readDeleted(dialog_id, text -> { if (!isFinished) presentFragment(new PakostnikTextActivity(currentAccount, "Удалённые сообщения", text)); }); return; }')
anchor='            headerItem = menu.addItem(chat_menu_options, otherIcon);'
assert s.count(anchor)==2
s=s.replace(anchor,anchor+'\n            if (currentEncryptedChat == null && currentUser != null && !currentUser.self && currentUser.id != 777000) headerItem.addSubItem(990702, R.drawable.msg_settings, "Удалённые сообщения");',1)
f.write_text(s)

# Filter remote deletion before both UI deletion and the storage deletion queue.
f=root/(java+'messenger/MessagesController.java')
s=f.read_text()
start=s.index('            } else if (baseUpdate instanceof TL_update.TL_updateDeleteMessages) {')
end=s.index('            } else if (baseUpdate instanceof TL_update.TL_updateDeleteQuickReplyMessages) {',start)
block=s[start:end]
old='                arrayList.addAll(update.messages);'
assert block.count(old)==1
block=block.replace(old,'''                final ArrayList<Integer> pakostnikRemoteIds = new ArrayList<>(update.messages);
                arrayList.addAll(org.telegram.messenger.pakostnik.RetainedMessages.get(currentAccount).filterRemote(0, pakostnikRemoteIds));
                AndroidUtilities.runOnUIThread(() -> {
                    org.telegram.messenger.pakostnik.LocalArchive.get(currentAccount).deleted(pakostnikRemoteIds);
                    org.telegram.messenger.pakostnik.PakostnikAI.get(currentAccount).onDeleted(pakostnikRemoteIds);
                    getNotificationCenter().postNotificationName(NotificationCenter.updateInterfaces, 0, "pakostnik_deleted");
                });''')
s=s[:start]+block+s[end:]
start=s.index('            } else if (baseUpdate instanceof TL_update.TL_updateDeleteChannelMessages) {')
end=s.index('            } else if (baseUpdate instanceof TL_update.TL_updateChannel) {',start)
block=s[start:end];assert block.count(old)==1
block=block.replace(old,'''                arrayList.addAll(org.telegram.messenger.pakostnik.RetainedMessages.get(currentAccount).filterRemote(update.channel_id, update.messages));
                AndroidUtilities.runOnUIThread(() -> getNotificationCenter().postNotificationName(NotificationCenter.updateInterfaces, 0, "pakostnik_deleted"));''')
s=s[:start]+block+s[end:];f.write_text(s)
edit(java+'messenger/MessagesController.java',
     '                if (newMessageCallback != null && newMessageCallback.onMessageReceived(message)) {',
     '                if (!(baseUpdate instanceof TL_update.TL_updateNewScheduledMessage)) org.telegram.messenger.pakostnik.RetainedMessages.get(currentAccount).remember(message);\n                if (newMessageCallback != null && newMessageCallback.onMessageReceived(message)) {')
edit(java+'messenger/MessagesController.java',
     '                    message.ttl_period = updates.ttl_period;\n                    message.media = new TLRPC.TL_messageMediaEmpty();',
     '                    message.ttl_period = updates.ttl_period;\n                    message.media = new TLRPC.TL_messageMediaEmpty();\n                    org.telegram.messenger.pakostnik.RetainedMessages.get(currentAccount).remember(message);')
edit(java+'messenger/MessagesController.java',
     '    public void deleteMessages(ArrayList<Integer> messages, ArrayList<Long> randoms, TLRPC.EncryptedChat encryptedChat, long dialogId, boolean forAll, int mode, boolean cacheOnly, long taskId, TLObject taskRequest, int topicId, boolean movedToScheduled, int movedToScheduledMessageId) {',
     '    public void deleteMessages(ArrayList<Integer> messages, ArrayList<Long> randoms, TLRPC.EncryptedChat encryptedChat, long dialogId, boolean forAll, int mode, boolean cacheOnly, long taskId, TLObject taskRequest, int topicId, boolean movedToScheduled, int movedToScheduledMessageId) {\n        if (mode == 0 && !cacheOnly) { org.telegram.messenger.pakostnik.RetainedMessages.get(currentAccount).forgetLocal(dialogId, messages); if (messages != null) org.telegram.messenger.pakostnik.LocalArchive.get(currentAccount).forgetLocal(dialogId, messages); }')
edit(java+'messenger/MessagesController.java',
     '    public void deleteDialog(final long did, int onlyHistory, boolean revoke) {',
     '    public void deleteDialog(final long did, int onlyHistory, boolean revoke) {\n        org.telegram.messenger.pakostnik.RetainedMessages.get(currentAccount).forgetDialog(did); org.telegram.messenger.pakostnik.LocalArchive.get(currentAccount).forgetLocal(did, null);')
edit(java+'ui/ChatActivity.java',
     '        } else if (id == NotificationCenter.updateInterfaces) {',
     '        } else if (id == NotificationCenter.updateInterfaces) {\n            if (args.length > 1 && "pakostnik_deleted".equals(args[1])) { for (MessageObject kept : messages) kept.forceUpdate = true; updateVisibleRows(); return; }')
edit(java+'ui/Cells/ChatMessageCell.java',
     '        timeTextWidth = timeWidth = (int) Math.ceil(Theme.chat_timePaint.measureText(currentTimeString, 0, currentTimeString == null ? 0 : currentTimeString.length()));',
     '        if (org.telegram.messenger.pakostnik.RetainedMessages.get(currentAccount).deleted(currentMessageObject.messageOwner)) currentTimeString = TextUtils.concat("✕ удалено · ", currentTimeString == null ? "" : currentTimeString);\n        timeTextWidth = timeWidth = (int) Math.ceil(Theme.chat_timePaint.measureText(currentTimeString, 0, currentTimeString == null ? 0 : currentTimeString.length()));')
edit(java+'messenger/FileLoader.java',
     '    public File getPathToMessage(TLRPC.Message message, boolean forceCache, boolean useFileDatabaseQueue) {',
     '    public File getPathToMessage(TLRPC.Message message, boolean forceCache, boolean useFileDatabaseQueue) {\n        File retained = org.telegram.messenger.pakostnik.RetainedMedia.get(currentAccount).retainedPath(message);\n        if (retained != null) return retained;')
edit(java+'messenger/FileLoader.java',
     '                    loadOperationPathsUI.remove(fileName);',
     '                    org.telegram.messenger.pakostnik.RetainedMedia.get(currentAccount).loaded(finalFile, parentObject);\n                    loadOperationPathsUI.remove(fileName);')
edit(java+'messenger/BuildVars.java','public static int APP_ID = 4;','public static int APP_ID = BuildConfig.PAKOSTNIK_API_ID;')
f=root/(java+'messenger/BuildVars.java')
s=f.read_text();s,n=re.subn(r'public static String APP_HASH = "[^"]*";', 'public static String APP_HASH = BuildConfig.PAKOSTNIK_API_HASH;',s);assert n==1
s=s.replace('public static boolean CHECK_UPDATES = true;', 'public static boolean CHECK_UPDATES = false;')
s=s.replace('public static boolean SUPPORTS_PASSKEYS = true;', 'public static boolean SUPPORTS_PASSKEYS = false;')
s=s.replace('public static boolean LOGS_ENABLED = BuildConfig.DEBUG_VERSION;', 'public static boolean LOGS_ENABLED = false;')
s=s.replace('LOGS_ENABLED = DEBUG_VERSION || sharedPreferences.getBoolean("logsEnabled", DEBUG_VERSION);','LOGS_ENABLED = false;')
f.write_text(s)
edit('TMessagesProj/build.gradle','    defaultConfig {','''    defaultConfig {
        def ownApiId = System.getenv('TG_API_ID') ?: '0'
        def ownApiHash = System.getenv('TG_API_HASH') ?: ''
        if (!(ownApiId ==~ /[1-9][0-9]{0,9}/) || !(ownApiHash ==~ /[a-fA-F0-9]{32}/)) {
            throw new GradleException('Set TG_API_ID and TG_API_HASH for your own Telegram application')
        }
        buildConfigField 'int', 'PAKOSTNIK_API_ID', ownApiId
        buildConfigField 'String', 'PAKOSTNIK_API_HASH', '"' + ownApiHash + '"'
''')
edit('gradle.properties','APP_PACKAGE=org.telegram.messenger','APP_PACKAGE=ai.pakostnik.client')
edit('gradle.properties','org.gradle.jvmargs=-Xmx8g -XX:MaxMetaspaceSize=1g','org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g\norg.gradle.workers.max=2')
# Keep each placeholder Firebase client's suffix, adapting to our application ID.
for f in root.rglob('google-services.json'):
    if '.git' not in f.parts:
        data=json.loads(f.read_text())
        for client in data.get('client',[]):
            info=client.get('client_info',{}).get('android_client_info',{})
            package=info.get('package_name','')
            if package.startswith('org.telegram.messenger'):
                info['package_name']=package.replace('org.telegram.messenger','ai.pakostnik.client',1)
        f.write_text(json.dumps(data,indent=2)+'\n')
# Distinct name and icon in the shared resources and standalone manifest.
for f in (root/'TMessagesProj/src/main/res').glob('values*/strings.xml'):
    s=f.read_text()
    s=re.sub(r'(<string name="AppName">).*?(</string>)',r'\1Pakostnik AI\2',s)
    s=re.sub(r'(<string name="AppNameBeta">).*?(</string>)',r'\1Pakostnik AI Beta\2',s)
    f.write_text(s)
for path in ['TMessagesProj/src/main/AndroidManifest.xml','TMessagesProj/config/release/AndroidManifest_standalone.xml']:
    f=root/path;s=f.read_text()
    s=re.sub(r'android:(icon|roundIcon)="@mipmap/[^"]+"',r'android:\1="@drawable/pakostnik_icon"',s)
    s=s.replace('android:allowBackup="true"','android:allowBackup="false"')
    f.write_text(s)
shutil.copytree(here/'overlay',root,dirs_exist_ok=True)
marker.write_text(BASE+'\n')
print('Pakostnik overlay applied to '+BASE)
