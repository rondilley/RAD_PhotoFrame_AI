package rad.photoframe.kiosk;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ComponentName;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.ByteArrayInputStream;
import java.util.Collections;

/**
 * Full-screen kiosk for one host origin (ARCHITECTURE section 13).
 * - Origin pin: navigations and resource loads to any other origin are refused (SR-11).
 * - Token: the cookie rf_token is set for the host origin before the first load (SR-05).
 * - Escape: one finger held still for 3 s in the 120 x 120 px top-left corner opens the
 *   menu (FR-07). Touches still go to the page.
 * - Host offline: a native screen covers the WebView error page and the kiosk retries (FR-16).
 * - No JavaScript bridge, no file or content access, no new windows.
 */
public class MainActivity extends Activity {
  static final String TAG = "RadKiosk";
  static final int CORNER_PX = 120;
  static final long HOLD_MS = 3000;
  static final float SLOP_PX = 40;
  static final long RETRY_MS = 5000;

  private final Handler handler = new Handler(Looper.getMainLooper());
  private WebView web;
  private OriginPin pin;
  private String hostUrl;
  private boolean pageFailed;
  private LinearLayout cover;
  private TextView coverTitle, coverText;
  private boolean holdArmed;
  private float holdX, holdY;

  private final Runnable retry = new Runnable() {
    @Override
    public void run() {
      if (hostUrl != null) web.loadUrl(hostUrl);
    }
  };

  private final Runnable openMenu = new Runnable() {
    @Override
    public void run() {
      holdArmed = false;
      Log.i(TAG, "corner hold: menu");
      new AlertDialog.Builder(MainActivity.this)
          .setTitle("RAD Frame")
          .setItems(new String[] {"Android Settings", "Wi-Fi settings", "Reload", "Open launcher"},
              (d, which) -> {
                if (which == 0) startActivity(new Intent(Settings.ACTION_SETTINGS));
                else if (which == 1) startActivity(new Intent(Settings.ACTION_WIFI_SETTINGS));
                else if (which == 2) reload();
                else openLauncher();
              })
          .setNegativeButton("Back to the dashboard", null)
          .show();
    }
  };

  @Override
  protected void onCreate(Bundle state) {
    super.onCreate(state);
    getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
    SharedPreferences p = Config.prefs(this);
    WebView.setWebContentsDebuggingEnabled(p.getBoolean(Config.DEBUG, false));
    keepNavEnabled();

    web = new WebView(this);
    WebSettings s = web.getSettings();
    s.setJavaScriptEnabled(true);
    s.setDomStorageEnabled(true);
    s.setAllowFileAccess(false);
    s.setAllowContentAccess(false);
    s.setAllowFileAccessFromFileURLs(false);
    s.setAllowUniversalAccessFromFileURLs(false);
    s.setGeolocationEnabled(false);
    s.setSupportMultipleWindows(false);
    s.setJavaScriptCanOpenWindowsAutomatically(false);
    s.setSaveFormData(false);
    s.setMediaPlaybackRequiresUserGesture(true);
    s.setUseWideViewPort(true);
    web.setWebViewClient(new PinnedClient());
    // A long press starts a text selection, which takes the touch from the corner hold.
    web.setLongClickable(false);
    web.setOnLongClickListener(v -> true);
    web.setHapticFeedbackEnabled(false);

    FrameLayout root = new FrameLayout(this);
    root.setBackgroundColor(Color.BLACK);
    root.addView(web);
    root.addView(buildCover());
    setContentView(root);

    hostUrl = p.getString(Config.HOST_URL, null);
    pin = OriginPin.of(hostUrl);
    String token = p.getString(Config.TOKEN, null);
    if (pin == null) {
      showCover("Not configured", "Set the host URL and the token with kiosk_install.ps1.");
      return;
    }
    CookieManager cm = CookieManager.getInstance();
    cm.setAcceptCookie(true);
    cm.setAcceptThirdPartyCookies(web, false);
    if (Config.validToken(token)) {
      cm.setCookie(pin.origin(), "rf_token=" + token + "; Path=/; HttpOnly");
      cm.flush();
    }
    Log.i(TAG, "start: origin " + pin.origin() + ", token " + (Config.validToken(token) ? "set" : "missing"));
    web.loadUrl(hostUrl);
  }

  private final class PinnedClient extends WebViewClient {
    @Override
    @SuppressWarnings("deprecation")
    public boolean shouldOverrideUrlLoading(WebView view, String url) {
      return refuse(url, "navigation");
    }

    @Override
    public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
      return refuse(req.getUrl().toString(), "navigation");
    }

    @Override
    public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
      if (!refuse(req.getUrl().toString(), "request")) return null;
      return new WebResourceResponse("text/plain", "utf-8", 403, "Forbidden",
          Collections.<String, String>emptyMap(), new ByteArrayInputStream(new byte[0]));
    }

    @Override
    public void onPageStarted(WebView view, String url, Bitmap icon) {
      pageFailed = false;
    }

    @Override
    public void onPageFinished(WebView view, String url) {
      if (!pageFailed && pin != null) cover.setVisibility(View.GONE);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onReceivedError(WebView view, int code, String desc, String failingUrl) {
      // API 23: called for the main frame only
      Log.w(TAG, "host offline (" + desc + "), retry in " + RETRY_MS + " ms");
      pageFailed = true;
      showCover("Host offline", "The frame cannot get to the host. It tries again each 5 seconds.");
      handler.removeCallbacks(retry);
      handler.postDelayed(retry, RETRY_MS);
    }
  }

  /** True when the URL is not on the pinned origin (and so is refused). */
  private boolean refuse(String url, String what) {
    if (pin != null && pin.allows(url)) return false;
    if ("about:blank".equals(url)) return false;
    Log.w(TAG, "origin pin: refused " + what + " " + safe(url));
    return true;
  }

  /** The URL without its query and fragment, for the log. */
  private static String safe(String url) {
    int q = url.indexOf('?');
    int h = url.indexOf('#');
    int cut = q < 0 ? h : (h < 0 ? q : Math.min(q, h));
    return cut < 0 ? url : url.substring(0, cut);
  }

  private void reload() {
    handler.removeCallbacks(retry);
    if (hostUrl != null) web.loadUrl(hostUrl);
  }

  private int dp(float v) {
    return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
  }

  private View buildCover() {
    cover = new LinearLayout(this);
    cover.setOrientation(LinearLayout.VERTICAL);
    cover.setGravity(Gravity.CENTER);
    cover.setBackgroundColor(Color.rgb(17, 17, 17));
    cover.setClickable(true);
    coverTitle = new TextView(this);
    coverTitle.setTextColor(Color.WHITE);
    coverTitle.setTextSize(TypedValue.COMPLEX_UNIT_SP, 40);
    coverTitle.setGravity(Gravity.CENTER);
    cover.addView(coverTitle);
    coverText = new TextView(this);
    coverText.setTextColor(Color.rgb(170, 170, 170));
    coverText.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
    coverText.setGravity(Gravity.CENTER);
    coverText.setPadding(dp(24), dp(12), dp(24), dp(12));
    cover.addView(coverText);
    coverTitle.setText("Starting");
    return cover;
  }

  private void showCover(String title, String text) {
    coverTitle.setText(title);
    coverText.setText(text);
    cover.setVisibility(View.VISIBLE);
  }

  private void openLauncher() {
    Intent home = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME);
    for (ResolveInfo info : getPackageManager().queryIntentActivities(home, 0)) {
      String pkg = info.activityInfo.packageName;
      if (pkg.equals(getPackageName()) || pkg.equals("com.android.settings")) continue;
      startActivity(new Intent(home).setComponent(new ComponentName(pkg, info.activityInfo.name)));
      return;
    }
    startActivity(new Intent(Settings.ACTION_SETTINGS));
  }

  /**
   * The frame has no navigation bar. NavService gives Back and Dashboard buttons outside the
   * kiosk. kiosk_install.ps1 grants WRITE_SECURE_SETTINGS, so the kiosk can put the service back
   * on the enabled list when the vendor software removes it.
   */
  private void keepNavEnabled() {
    if (checkSelfPermission("android.permission.WRITE_SECURE_SETTINGS") != PackageManager.PERMISSION_GRANTED) return;
    ComponentName want = new ComponentName(this, NavService.class);
    String cur = Settings.Secure.getString(getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
    boolean listed = false;
    if (cur != null) {
      for (String entry : cur.split(":")) {
        if (want.equals(ComponentName.unflattenFromString(entry))) listed = true;
      }
    }
    // The frame clears accessibility_enabled even when the service stays on the list.
    boolean on = "1".equals(Settings.Secure.getString(getContentResolver(), Settings.Secure.ACCESSIBILITY_ENABLED));
    if (listed && on) return;
    try {
      if (!listed) {
        String next = cur == null || cur.isEmpty() ? want.flattenToString() : cur + ":" + want.flattenToString();
        Settings.Secure.putString(getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES, next);
      }
      Settings.Secure.putString(getContentResolver(), Settings.Secure.ACCESSIBILITY_ENABLED, "1");
      Log.i(TAG, "navigation service enabled (listed " + listed + ", switch " + on + ")");
    } catch (SecurityException e) {
      Log.w(TAG, "cannot enable the navigation service", e);
    }
  }

  @Override
  protected void onResume() {
    super.onResume();
    NavService.setKioskVisible(true);
  }

  @Override
  protected void onPause() {
    cancelHold();
    NavService.setKioskVisible(false);
    super.onPause();
  }

  @Override
  protected void onDestroy() {
    handler.removeCallbacksAndMessages(null);
    if (web != null) web.destroy();
    super.onDestroy();
  }

  /** The corner hold. All touches still go to the page. */
  @Override
  public boolean dispatchTouchEvent(MotionEvent e) {
    switch (e.getActionMasked()) {
      case MotionEvent.ACTION_DOWN:
        if (e.getX() < CORNER_PX && e.getY() < CORNER_PX) {
          holdArmed = true;
          holdX = e.getX();
          holdY = e.getY();
          handler.removeCallbacks(openMenu);
          handler.postDelayed(openMenu, HOLD_MS);
        }
        break;
      case MotionEvent.ACTION_MOVE:
        if (holdArmed && Math.hypot(e.getX() - holdX, e.getY() - holdY) > SLOP_PX) cancelHold();
        break;
      case MotionEvent.ACTION_POINTER_DOWN:
      case MotionEvent.ACTION_UP:
      case MotionEvent.ACTION_CANCEL:
        cancelHold();
        break;
      default:
        break;
    }
    return super.dispatchTouchEvent(e);
  }

  private void cancelHold() {
    if (!holdArmed) return;
    holdArmed = false;
    handler.removeCallbacks(openMenu);
  }

  @Override
  public void onWindowFocusChanged(boolean hasFocus) {
    super.onWindowFocusChanged(hasFocus);
    if (hasFocus) {
      getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
          | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_FULLSCREEN
          | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
          | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }
  }

  @Override
  public void onBackPressed() {
    // stay on the dashboard
  }
}
