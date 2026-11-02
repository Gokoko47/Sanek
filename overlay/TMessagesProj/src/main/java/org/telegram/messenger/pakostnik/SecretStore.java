package org.telegram.messenger.pakostnik;
import android.content.*;
import android.security.keystore.*;
import android.util.Base64;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import java.security.KeyStore;
final class SecretStore {
 private final android.content.SharedPreferences prefs;
 SecretStore(Context c) { prefs=c.getSharedPreferences("vault",0); }
 private javax.crypto.SecretKey key() throws Exception {
  KeyStore k=KeyStore.getInstance("AndroidKeyStore"); k.load(null);
  if(!k.containsAlias("pakostnik")) { KeyGenerator g=KeyGenerator.getInstance("AES","AndroidKeyStore"); g.init(new KeyGenParameterSpec.Builder("pakostnik",KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes("GCM").setEncryptionPaddings("NoPadding").build()); g.generateKey(); }
  return (javax.crypto.SecretKey)k.getKey("pakostnik",null);
 }
 void set(String name,String value) throws Exception { Cipher c=Cipher.getInstance("AES/GCM/NoPadding"); c.init(Cipher.ENCRYPT_MODE,key()); prefs.edit().putString(name,Base64.encodeToString(c.getIV(),2)+":"+Base64.encodeToString(c.doFinal(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)),2)).commit(); }
 String get(String name) { try { String[] v=prefs.getString(name,"").split(":"); if(v.length!=2)return ""; Cipher c=Cipher.getInstance("AES/GCM/NoPadding"); c.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Base64.decode(v[0],2))); return new String(c.doFinal(Base64.decode(v[1],2)),java.nio.charset.StandardCharsets.UTF_8); } catch(Exception e){return "";} }
}
