package org.telegram.ui;
import android.content.Context;
import android.graphics.Typeface;
import android.view.View;
import android.widget.*;
import org.telegram.messenger.AndroidUtilities;
import org.telegram.ui.ActionBar.*;
/** Selectable device-only view for archived text and transcription results. */
public final class PakostnikTextActivity extends BaseFragment {
 private final String title,text;
 public PakostnikTextActivity(int account,String title,String text){currentAccount=account;this.title=title;this.text=text;}
 @Override public View createView(Context c){actionBar.setTitle(title);actionBar.setBackButtonImage(org.telegram.messenger.R.drawable.ic_ab_back);actionBar.setActionBarMenuOnItemClick(new ActionBar.ActionBarMenuOnItemClick(){@Override public void onItemClick(int id){if(id==-1)finishFragment();}});ScrollView scroll=new ScrollView(c);scroll.setBackgroundColor(0xff080808);TextView content=new TextView(c);content.setTextColor(0xffeeeeee);content.setTextSize(15);content.setTypeface(Typeface.MONOSPACE);content.setTextIsSelectable(true);int p=AndroidUtilities.dp(20);content.setPadding(p,p,p,p);content.setText(text);scroll.addView(content);fragmentView=scroll;return scroll;}
}
