package com.ninjatap.touchtest;

import android.app.Activity;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Bundle;
import android.util.Log;
import android.view.MotionEvent;
import android.view.View;

import java.io.OutputStreamWriter;
import java.util.Locale;

public class TouchActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(new TouchView(this));
    }

    static final class TouchView extends View {
        private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint dot = new Paint(Paint.ANTI_ALIAS_FLAG);
        private String status = "ready";
        private String axes = "pressure and size will show here";
        private float span0 = -1f;
        private final float[] xs = new float[10];
        private final float[] ys = new float[10];
        private int pointerCount;
        private final OutputStreamWriter out;

        TouchView(Activity activity) {
            super(activity);
            text.setColor(Color.WHITE);
            text.setTextSize(42f);
            dot.setColor(Color.parseColor("#3DDC97"));
            setBackgroundColor(Color.BLACK);
            OutputStreamWriter writer = null;
            try {
                writer = new OutputStreamWriter(activity.openFileOutput("motion.log", Activity.MODE_PRIVATE));
                writer.write("action n id x y pressure size touchMajor touchMinor orientation toolMajor toolMinor history\n");
                writer.flush();
            } catch (Exception ignored) {
                writer = null;
            }
            out = writer;
        }

        @Override
        public boolean onTouchEvent(MotionEvent event) {
            int action = event.getActionMasked();
            pointerCount = event.getPointerCount();
            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
                pointerCount = 0;
                span0 = -1f;
            }
            StringBuilder line = new StringBuilder();
            line.append("action=").append(actionName(action));
            line.append(" n=").append(event.getPointerCount());
            line.append(" hist=").append(event.getHistorySize());
            StringBuilder axesLine = new StringBuilder();
            for (int i = 0; i < event.getPointerCount() && i < xs.length; i++) {
                xs[i] = event.getRawX(i);
                ys[i] = event.getRawY(i);
                int id = event.getPointerId(i);
                float pressure = event.getPressure(i);
                float size = event.getSize(i);
                float touchMajor = event.getTouchMajor(i);
                float touchMinor = event.getTouchMinor(i);
                float orientation = event.getOrientation(i);
                float toolMajor = event.getToolMajor(i);
                float toolMinor = event.getToolMinor(i);
                line.append(" p").append(id)
                        .append("=").append((int) xs[i]).append(",").append((int) ys[i])
                        .append(" pr=").append(fmt(pressure))
                        .append(" sz=").append(fmt(size))
                        .append(" maj=").append(fmt(touchMajor))
                        .append(" min=").append(fmt(touchMinor))
                        .append(" ori=").append(fmt(orientation))
                        .append(" tool=").append(fmt(toolMajor)).append("/").append(fmt(toolMinor));
                if (axesLine.length() > 0) {
                    axesLine.append("   ");
                }
                axesLine.append("p").append(id)
                        .append(" pr ").append(fmt(pressure))
                        .append("  sz ").append(fmt(size))
                        .append("  maj ").append(Math.round(touchMajor));
            }
            if (event.getPointerCount() >= 2) {
                float dx = event.getRawX(0) - event.getRawX(1);
                float dy = event.getRawY(0) - event.getRawY(1);
                float span = (float) Math.hypot(dx, dy);
                if (action == MotionEvent.ACTION_POINTER_DOWN || span0 < 0f) {
                    span0 = span;
                }
                line.append(" span=").append((int) span);
                if (span0 > 1f) {
                    line.append(" scale=").append(String.format("%.2f", span / span0));
                }
            }
            status = "action=" + actionName(action) + " n=" + event.getPointerCount();
            axes = axesLine.length() == 0 ? "no pointers" : axesLine.toString();
            Log.i("NinjaTapTouch", line.toString());
            if (out != null) {
                try {
                    out.write(line.toString());
                    out.write("\n");
                    out.flush();
                } catch (Exception ignored) {
                }
            }
            invalidate();
            return true;
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            canvas.drawText("logging pressure and size", 48f, 120f, text);
            canvas.drawText(status, 48f, 190f, text);
            canvas.drawText(axes, 48f, 260f, text);
            for (int i = 0; i < pointerCount; i++) {
                canvas.drawCircle(xs[i], ys[i], 48f, dot);
            }
        }

        private static String actionName(int action) {
            switch (action) {
                case MotionEvent.ACTION_DOWN:
                    return "DOWN";
                case MotionEvent.ACTION_UP:
                    return "UP";
                case MotionEvent.ACTION_MOVE:
                    return "MOVE";
                case MotionEvent.ACTION_POINTER_DOWN:
                    return "POINTER_DOWN";
                case MotionEvent.ACTION_POINTER_UP:
                    return "POINTER_UP";
                case MotionEvent.ACTION_CANCEL:
                    return "CANCEL";
                default:
                    return String.valueOf(action);
            }
        }

        private static String fmt(float value) {
            return String.format(Locale.US, "%.3f", value);
        }
    }
}
