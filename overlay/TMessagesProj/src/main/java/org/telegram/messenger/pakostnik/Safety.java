package org.telegram.messenger.pakostnik;
import java.util.regex.Pattern;
final class Safety {
 private static final Pattern RISK=Pattern.compile("(?iu)(парол|password|passcode|секрет|secret|токен|token|код.{0,16}(вход|подтверж|авториз)|\\b(otp|pin|cvv|cvc|2fa)\\b|\\b\\d{4,}\\b|перев[её]д.{0,12}(деньг|руб)|деньг|рубл|кредит|займ|оплат|payment|money|банк|bank|договор|contract|обязую|гарантир|guarantee|согласие|consent|диагноз|diagnos|лекарств|уволь|женись|marry|развод|delete|удали|инструкци|system prompt|ignore.{0,20}instruct)");
 static boolean blocked(String text){return text.length()>4000||RISK.matcher(text).find();}
}
