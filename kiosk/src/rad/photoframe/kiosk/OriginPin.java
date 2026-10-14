package rad.photoframe.kiosk;

import java.net.URI;
import java.util.Locale;

/** One http or https origin. The kiosk loads only URLs on this origin (SR-11). */
final class OriginPin {
  final String scheme;
  final String host;
  final int port;

  private OriginPin(String scheme, String host, int port) {
    this.scheme = scheme;
    this.host = host;
    this.port = port;
  }

  /** The origin of an http or https URL, or null for any other URL. */
  static OriginPin of(String url) {
    if (url == null) return null;
    URI u;
    try {
      u = new URI(url.trim());
    } catch (Exception e) {
      return null;
    }
    String scheme = u.getScheme() == null ? null : u.getScheme().toLowerCase(Locale.ROOT);
    if (!"http".equals(scheme) && !"https".equals(scheme)) return null;
    if (u.getRawUserInfo() != null) return null; // no user:pass@host forms
    String host = u.getHost();
    if (host == null || host.isEmpty()) return null;
    int port = u.getPort();
    if (port == -1) port = "https".equals(scheme) ? 443 : 80;
    return new OriginPin(scheme, host.toLowerCase(Locale.ROOT), port);
  }

  boolean allows(String url) {
    OriginPin o = of(url);
    return o != null && o.scheme.equals(scheme) && o.host.equals(host) && o.port == port;
  }

  /** scheme://host:port, for the cookie. */
  String origin() {
    return scheme + "://" + host + ":" + port;
  }
}
