package de.readerportal.nikowashere;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.AsyncTask;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import org.xmlpull.v1.XmlPullParser;
import org.xmlpull.v1.XmlPullParserFactory;

import java.io.BufferedInputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public final class BlogActivity extends Activity {
    private static final String ARTICLE_URL = "https://nikolan.net/posts/fixing-ipads/";
    private static final String FEED_URL = "https://nikolan.net/blog/index.xml";
    private static final int HOLO_BLUE = Color.rgb(51, 181, 229);

    private LinearLayout screen;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (getActionBar() != null) {
            getActionBar().setTitle("Niko's Blog");
            getActionBar().setSubtitle(null);
            getActionBar().setDisplayHomeAsUpEnabled(true);
        }
        showLoading();
        fetchArticle();
    }

    @Override
    public boolean onNavigateUp() {
        finish();
        return true;
    }

    private void makeScreen() {
        screen = new LinearLayout(this);
        screen.setOrientation(LinearLayout.VERTICAL);
        screen.setGravity(Gravity.CENTER);
        screen.setPadding(dp(20), dp(20), dp(20), dp(20));
        screen.setBackgroundColor(Color.rgb(16, 16, 16));
        setContentView(screen);
    }

    private void showLoading() {
        makeScreen();
        ProgressBar progress = new ProgressBar(this);
        screen.addView(progress);
        TextView message = message("Fetching the post…", Color.LTGRAY);
        screen.addView(message, wrap());
    }

    private void showError(String detail) {
        makeScreen();
        TextView heading = message("Couldn't load the blog post", Color.WHITE);
        heading.setTextSize(20);
        screen.addView(heading, wrap());

        TextView reason = message(detail, Color.LTGRAY);
        LinearLayout.LayoutParams reasonParams = wrap();
        reasonParams.setMargins(0, dp(12), 0, dp(16));
        screen.addView(reason, reasonParams);

        Button retry = new Button(this);
        retry.setText("RETRY");
        retry.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                showLoading();
                fetchArticle();
            }
        });
        screen.addView(retry, wrap());
    }

    private void showArticle(final Article article) {
        if (getActionBar() != null) {
            getActionBar().setTitle(article.title);
        }

        WebView webView = new WebView(this);
        webView.setBackgroundColor(Color.rgb(16, 16, 16));
        webView.getSettings().setJavaScriptEnabled(false);
        webView.getSettings().setBuiltInZoomControls(true);
        webView.getSettings().setDisplayZoomControls(false);
        webView.getSettings().setLoadWithOverviewMode(false);
        webView.getSettings().setDefaultFontSize(18);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                return true;
            }
        });

        String html = "<!doctype html><html><head>"
                + "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                + "<style>"
                + "html{background:#101010;color:#eee;font-family:sans-serif;}"
                + "body{margin:0;padding:20px;line-height:1.45;}"
                + "h1,h2,h3,a{color:#33b5e5;} h1{font-size:27px;} h2{font-size:23px;margin-top:1.4em;}"
                + "img,video{max-width:100%;height:auto;} blockquote{border-left:3px solid #33b5e5;margin-left:0;padding-left:14px;color:#ccc;}"
                + "pre{overflow:auto;background:#222;padding:10px;} code{font-family:monospace;}"
                + "</style></head><body><h1>" + escapeHtml(article.title) + "</h1>"
                + article.html + "</body></html>";
        webView.loadDataWithBaseURL(ARTICLE_URL, html, "text/html", "UTF-8", null);
        setContentView(webView, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private void fetchArticle() {
        new AsyncTask<Void, Void, Article>() {
            private String error;

            @Override
            protected Article doInBackground(Void... ignored) {
                HttpURLConnection connection = null;
                try {
                    connection = (HttpURLConnection) new URL(FEED_URL).openConnection();
                    connection.setConnectTimeout(15000);
                    connection.setReadTimeout(20000);
                    connection.setRequestProperty("Accept", "application/rss+xml, application/xml, text/xml");
                    connection.setRequestProperty("User-Agent", "NikoWasHere/1.0 (Android RSS reader)");
                    int status = connection.getResponseCode();
                    if (status < 200 || status >= 300) {
                        throw new Exception("The server returned HTTP " + status + ".");
                    }
                    InputStream input = new BufferedInputStream(connection.getInputStream());
                    try {
                        Article article = parseFeed(input);
                        if (article == null) {
                            throw new Exception("The selected post isn't in the RSS feed.");
                        }
                        return article;
                    } finally {
                        input.close();
                    }
                } catch (Exception exception) {
                    error = exception.getMessage();
                    if (error == null || error.length() == 0) {
                        error = exception.getClass().getSimpleName();
                    }
                    return null;
                } finally {
                    if (connection != null) {
                        connection.disconnect();
                    }
                }
            }

            @Override
            protected void onPostExecute(Article article) {
                if (isFinishing()) {
                    return;
                }
                if (article == null) {
                    showError(error);
                } else {
                    showArticle(article);
                }
            }
        }.execute();
    }

    private Article parseFeed(InputStream input) throws Exception {
        XmlPullParser parser = XmlPullParserFactory.newInstance().newPullParser();
        parser.setInput(input, "UTF-8");
        boolean inItem = false;
        String title = null;
        String link = null;
        String html = null;

        for (int event = parser.getEventType(); event != XmlPullParser.END_DOCUMENT; event = parser.next()) {
            if (event == XmlPullParser.START_TAG) {
                String name = parser.getName();
                if ("item".equals(name)) {
                    inItem = true;
                    title = null;
                    link = null;
                    html = null;
                } else if (inItem && "title".equals(name)) {
                    title = parser.nextText();
                } else if (inItem && "link".equals(name)) {
                    link = parser.nextText();
                } else if (inItem && ("encoded".equals(name) || "content:encoded".equals(name))) {
                    html = parser.nextText();
                }
            } else if (event == XmlPullParser.END_TAG && "item".equals(parser.getName())) {
                if (sameArticle(link, ARTICLE_URL)) {
                    return new Article(title == null ? "Blog post" : title, html == null ? "" : html);
                }
                inItem = false;
            }
        }
        return null;
    }

    private boolean sameArticle(String left, String right) {
        if (left == null || right == null) {
            return false;
        }
        return trimSlash(left).equals(trimSlash(right));
    }

    private String trimSlash(String value) {
        while (value.endsWith("/")) {
            value = value.substring(0, value.length() - 1);
        }
        return value;
    }

    private String escapeHtml(String value) {
        return value.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;");
    }

    private TextView message(String text, int color) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(color);
        view.setTextSize(16);
        view.setGravity(Gravity.CENTER);
        return view;
    }

    private LinearLayout.LayoutParams wrap() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static final class Article {
        final String title;
        final String html;

        Article(String title, String html) {
            this.title = title;
            this.html = html;
        }
    }
}
