package rad.photoframe.kiosk;

/** Host check of OriginPin (SR-11). Exit code 1 on the first wrong answer. */
public final class OriginPinCheck {
  private static int fails;

  private static void expect(boolean got, boolean want, String what) {
    if (got != want) {
      System.out.println("FAIL " + what + ": got " + got);
      fails++;
    }
  }

  public static void main(String[] args) {
    OriginPin p = OriginPin.of("http://127.0.0.1:8765/frame");
    expect(p != null, true, "parse host URL");
    expect(p.origin().equals("http://127.0.0.1:8765"), true, "origin string");

    expect(p.allows("http://127.0.0.1:8765/v1/now?shown=abc"), true, "same origin, path and query");
    expect(p.allows("HTTP://127.0.0.1:8765/static/a.css"), true, "scheme case");
    expect(p.allows("http://127.0.0.1:8765"), true, "no path");

    expect(p.allows("http://localhost:8765/frame"), false, "other host name, same address");
    expect(p.allows("http://127.0.0.1:8766/frame"), false, "other port");
    expect(p.allows("https://127.0.0.1:8765/frame"), false, "other scheme");
    expect(p.allows("http://127.0.0.1/frame"), false, "default port 80");
    expect(p.allows("http://127.0.0.1:8765@evil.example/frame"), false, "user info trick");
    expect(p.allows("http://evil.example/?u=http://127.0.0.1:8765/"), false, "origin in the query");
    expect(p.allows("file:///sdcard/a.html"), false, "file URL");
    expect(p.allows("javascript:alert(1)"), false, "javascript URL");
    expect(p.allows("data:text/html,x"), false, "data URL");
    expect(p.allows("intent://x#Intent;end"), false, "intent URL");
    expect(p.allows(null), false, "null");
    expect(p.allows("http://127.0.0.1:8765\\@evil.example/"), false, "backslash trick");

    OriginPin d = OriginPin.of("http://192.168.50.10/frame");
    expect(d.allows("http://192.168.50.10:80/x"), true, "explicit default port");
    expect(OriginPin.of("https://h.example/").allows("https://h.example:443/"), true, "https default port");
    expect(OriginPin.of("ftp://h.example/") == null, true, "ftp is not a web origin");
    expect(OriginPin.of("http://user:pw@h.example/") == null, true, "host URL with user info");

    if (fails > 0) {
      System.out.println("OriginPin check: " + fails + " failed");
      System.exit(1);
    }
    System.out.println("OriginPin check: all cases correct");
  }
}
