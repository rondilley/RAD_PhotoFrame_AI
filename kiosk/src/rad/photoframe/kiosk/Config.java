package rad.photoframe.kiosk;

import android.content.Context;
import android.content.SharedPreferences;

/** Kiosk settings. Only ConfigActivity writes them; it is not exported, so only root (ADB) can start it. */
final class Config {
  static final String PREFS = "kiosk";
  static final String HOST_URL = "host_url";
  static final String TOKEN = "token";
  static final String DEBUG = "debug";

  static SharedPreferences prefs(Context c) {
    return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
  }

  static boolean validToken(String t) {
    return t != null && t.matches("[A-Za-z0-9_-]{16,128}");
  }

  private Config() {}
}
