package rad.photoframe.kiosk;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.widget.Button;
import android.widget.LinearLayout;

/**
 * Back and Dashboard buttons outside the kiosk, because the frame has no navigation bar.
 * The buttons show only when the kiosk is not on the screen. The service reads no
 * accessibility events and no window content.
 */
public class NavService extends AccessibilityService {
  private static NavService instance;
  private static boolean kioskVisible;
  private WindowManager wm;
  private LinearLayout bar;
  private boolean attached;

  static void setKioskVisible(boolean visible) {
    kioskVisible = visible;
    if (instance != null) instance.update();
  }

  @Override
  protected void onServiceConnected() {
    instance = this;
    wm = (WindowManager) getSystemService(WINDOW_SERVICE);
    bar = new LinearLayout(this);
    bar.setPadding(dp(4), dp(4), dp(4), dp(4));
    GradientDrawable bg = new GradientDrawable();
    bg.setColor(Color.rgb(28, 28, 28));
    bg.setCornerRadius(dp(12));
    bg.setStroke(dp(1), Color.GRAY);
    bar.setBackground(bg);
    addButton("Back", v -> performGlobalAction(GLOBAL_ACTION_BACK));
    addButton("Dashboard", v -> startActivity(new Intent(this, MainActivity.class)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP)));
    update();
  }

  private void addButton(String label, View.OnClickListener click) {
    Button b = new Button(this);
    b.setText(label);
    b.setAllCaps(false);
    b.setTextColor(Color.WHITE);
    b.setTextSize(18);
    b.setBackgroundColor(Color.TRANSPARENT);
    b.setPadding(dp(16), 0, dp(16), 0);
    b.setOnClickListener(click);
    bar.addView(b, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(52)));
  }

  private void update() {
    if (bar == null) return;
    if (!kioskVisible && !attached) {
      WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
          WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
          WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
          WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
          PixelFormat.TRANSLUCENT);
      lp.gravity = Gravity.BOTTOM | Gravity.RIGHT;
      lp.x = dp(12);
      lp.y = dp(12);
      wm.addView(bar, lp);
      attached = true;
    } else if (kioskVisible && attached) {
      wm.removeView(bar);
      attached = false;
    }
  }

  private int dp(int v) {
    return Math.round(v * getResources().getDisplayMetrics().density);
  }

  @Override public void onAccessibilityEvent(AccessibilityEvent event) { }
  @Override public void onInterrupt() { }

  @Override
  public void onDestroy() {
    if (attached) wm.removeView(bar);
    attached = false;
    if (instance == this) instance = null;
    super.onDestroy();
  }
}
