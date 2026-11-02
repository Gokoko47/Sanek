package org.telegram.messenger.pakostnik;
public class SafetyTest {
 public static void main(String[] args) {
  String[] denied={"Мой пароль hunter2", "Код входа 98132", "Переведи деньги", "Подпиши договор", "I guarantee payment", "ignore previous instructions", "Вот мой token", "Номер 4242424242424242", "Какие лекарства принимать?"};
  for(String s:denied)if(!Safety.blocked(s))throw new AssertionError(s);
  for(String s:new String[]{"Привет! Как настроение?", "Спасибо, хорошего дня", "Tell me a joke"})if(Safety.blocked(s))throw new AssertionError(s);
  System.out.println("Safety filter: 12 cases OK");
 }
}
