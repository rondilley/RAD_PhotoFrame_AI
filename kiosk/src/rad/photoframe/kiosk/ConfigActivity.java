package rad.photoframe.kiosk;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.util.Log;

/**
 * Sets the kiosk settings from root ADB. Not exported: other apps cannot start it.
 *   am start -n rad.photoframe.kiosk/.ConfigActivity --es host_url http://HOST:PORT/frame --es token TOKEN
 * Optional: --ez home true|false (Home alias), --ez debug true|false (WebView remote debugging).
 * The token is never logged.
 */
public class ConfigActivity extends Activity {
  @Override
  protected void onCreate(Bundle state) {
    super.onCreate(state);
    Intent in = getIntent();
    SharedPreferences.Editor e = Config.prefs(this).edit();
    boolean ok = true;

    String url = in.getStringExtra(Config.HOST_URL);
    if (url != null) {
      if (OriginPin.of(url) != null) {
        e.putString(Config.HOST_URL, url.trim());
        Log.i(MainActivity.TAG, "config: host_url " + url.trim());
      } else {
        Log.w(MainActivity.TAG, "config: refused host_url (not http or https)");
        ok = false;
      }
    }
    String token = in.getStringExtra(Config.TOKEN);
    if (token != null) {
      if (Config.validToken(token)) {
        e.putString(Config.TOKEN, token);
        Log.i(MainActivity.TAG, "config: token set (" + token.length() + " characters)");
      } else {
        Log.w(MainActivity.TAG, "config: refused token (16 to 128 of A-Z a-z 0-9 _ -)");
        ok = false;
      }
    }
    if (in.hasExtra(Config.DEBUG)) {
      e.putBoolean(Config.DEBUG, in.getBooleanExtra(Config.DEBUG, false));
    }
    if (in.hasExtra("home")) {
      boolean home = in.getBooleanExtra("home", false);
      getPackageManager().setComponentEnabledSetting(new ComponentName(this, getPackageName() + ".Home"),
          home ? PackageManager.COMPONENT_ENABLED_STATE_ENABLED : PackageManager.COMPONENT_ENABLED_STATE_DEFAULT,
          PackageManager.DONT_KILL_APP);
      Log.i(MainActivity.TAG, "config: Home alias " + (home ? "on" : "off"));
    }
    e.commit();
    Log.i(MainActivity.TAG, "config: " + (ok ? "saved" : "saved with refusals"));

    startActivity(new Intent(this, MainActivity.class)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
    finish();
  }
}
