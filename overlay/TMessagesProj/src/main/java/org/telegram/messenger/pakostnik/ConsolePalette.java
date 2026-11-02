package org.telegram.messenger.pakostnik;

/** Color rules shared by the preview and Telegram theme; no Android dependencies. */
public final class ConsolePalette {
 private ConsolePalette(){}
 public static int parse(String value){String s=value.trim();if(s.startsWith("#"))s=s.substring(1);if(!s.matches("[a-fA-F0-9]{6}"))throw new IllegalArgumentException("Use RRGGBB");return 0xff000000|Integer.parseInt(s,16);}
 public static String hex(int color){return String.format(java.util.Locale.ROOT,"#%06X",color&0xffffff);}
 public static int gray(int color){int v=(int)Math.round(((color>>16)&255)*.2126+((color>>8)&255)*.7152+(color&255)*.0722);return (color&0xff000000)|(v<<16)|(v<<8)|v;}
 private static double linear(int c){double x=c/255.0;return x<=.04045?x/12.92:Math.pow((x+.055)/1.055,2.4);}
 public static double luminance(int color){return .2126*linear((color>>16)&255)+.7152*linear((color>>8)&255)+.0722*linear(color&255);}
 public static double contrast(int a,int b){double x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
 public static void validate(int background,int accent){if(luminance(background)>.08||contrast(surface(background,.065),accent)<4.5)throw new IllegalArgumentException("A dark background and a readable accent are required");}
 public static int surface(int background,double light){int r=(int)(((background>>16)&255)*(1-light)+255*light),g=(int)(((background>>8)&255)*(1-light)+255*light),b=(int)((background&255)*(1-light)+255*light);return 0xff000000|(r<<16)|(g<<8)|b;}
}
