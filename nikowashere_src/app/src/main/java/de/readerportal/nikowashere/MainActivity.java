package de.readerportal.nikowashere;

import android.app.Activity;
import android.graphics.Color;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.Button;
import android.widget.ScrollView;
import android.widget.TextView;

public final class MainActivity extends Activity {
    // ---------------------------------------------------------------------
    // APP'S VISIBLE TEXT
    // ---------------------------------------------------------------------
    private static final String APP_TITLE = "Niko Was Here";
    private static final String HEADING = "NIKO WAS HERE";
    private static final String MESSAGE =
            "Hi. My name is Niko and I am the reason this tablet is currently working.";
    private static final String EXPLANATION =
            "After the company that made this tablet went bankrupt, this tablet's activation servers were shut down too. "
            + "I got my hands on one of the tablets affected and this annoyed me. "
            + "So I decided to rebuild the server so all 100K+ units sold work again. "
            + "Feel free to delete this app.";
    private static final String FOOTER =
            "Learn more on my blog post at nikolan.net/posts/fixing-ipads/ on a modern device, or by clicking the button below.";
    private static final String BLOG_BUTTON = "READ THE BLOG POST";

    private static final int HOLO_BLUE = Color.rgb(51, 181, 229);
    private static final int TEXT_PRIMARY = Color.rgb(245, 245, 245);
    private static final int TEXT_SECONDARY = Color.rgb(190, 190, 190);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        if (getActionBar() != null) {
            getActionBar().setTitle(APP_TITLE);
            getActionBar().setSubtitle(null);
            getActionBar().setDisplayShowHomeEnabled(false);
            getActionBar().setDisplayUseLogoEnabled(false);
        }

        ScrollView scrollView = new ScrollView(this);
        scrollView.setFillViewport(true);
        scrollView.setBackgroundColor(Color.rgb(16, 16, 16));

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setGravity(Gravity.CENTER_HORIZONTAL);
        content.setPadding(dp(24), dp(28), dp(24), dp(24));
        scrollView.addView(content, new ScrollView.LayoutParams(
                ScrollView.LayoutParams.MATCH_PARENT,
                ScrollView.LayoutParams.WRAP_CONTENT));

        TextView heading = text(HEADING, 32, HOLO_BLUE);
        heading.setGravity(Gravity.CENTER);
        content.addView(heading, matchWrap());

        TextView message = text(MESSAGE, 20, TEXT_PRIMARY);
        message.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams messageParams = matchWrap();
        messageParams.setMargins(0, dp(18), 0, dp(24));
        content.addView(message, messageParams);

        TextView details = text(deviceDetails(), 16, TEXT_PRIMARY);
        details.setBackgroundResource(R.drawable.info_panel);
        details.setPadding(dp(18), dp(16), dp(18), dp(16));
        details.setLineSpacing(0, 1.2f);
        content.addView(details, matchWrap());

        TextView explanation = text(EXPLANATION, 16, TEXT_SECONDARY);
        explanation.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams explanationParams = matchWrap();
        explanationParams.setMargins(0, dp(24), 0, 0);
        content.addView(explanation, explanationParams);

        TextView footer = text(FOOTER, 14, HOLO_BLUE);
        footer.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams footerParams = matchWrap();
        footerParams.setMargins(0, dp(28), 0, 0);
        content.addView(footer, footerParams);

        Button blogButton = new Button(this);
        blogButton.setText(BLOG_BUTTON);
        blogButton.setTextColor(TEXT_PRIMARY);
        blogButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                startActivity(new Intent(MainActivity.this, BlogActivity.class));
            }
        });
        LinearLayout.LayoutParams buttonParams = matchWrap();
        buttonParams.setMargins(0, dp(16), 0, 0);
        content.addView(blogButton, buttonParams);

        LinearLayout screen = new LinearLayout(this);
        screen.setOrientation(LinearLayout.VERTICAL);
        screen.setBackgroundColor(Color.rgb(16, 16, 16));

        View holoDivider = new View(this);
        holoDivider.setBackgroundColor(HOLO_BLUE);
        screen.addView(holoDivider, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(2)));
        screen.addView(scrollView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));

        setContentView(screen);
    }

    private String deviceDetails() {
        return "Manufacturer: " + Build.MANUFACTURER
                + "\nModel: " + Build.MODEL
                + "\nAndroid: " + Build.VERSION.RELEASE
                + " (API " + Build.VERSION.SDK_INT + ")"
                + "\nBuild: " + Build.DISPLAY;
    }

    private TextView text(String value, int sizeSp, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        styleText(view, sizeSp, color);
        return view;
    }

    private void styleText(TextView view, int sizeSp, int color) {
        view.setTextSize(sizeSp);
        view.setTextColor(color);
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
