"""
The glass layer: a real macOS floating widget for Sleight.

OpenCV can only give us an opaque rectangle with a title bar. A product-grade
dock widget needs the opposite of that - no chrome, a transparent background,
a frosted pill, always on top, and it must never steal focus from the app the
user is actually controlling.

That is an NSWindow, so this module is the only place that talks to AppKit:

    pill = GlassPill(on_key=...)         # falls back to None-safe .ok = False
    pill.set_pill(x, y, w, h)            # where the frosted capsule sits
    pill.paint(rgba)                     # numpy HxWx4, drawn above the glass
    pill.tick()                          # let AppKit breathe, ~1 frame

Everything is driven from the caller's own loop - we never call NSApp.run(),
because the camera loop owns the main thread.
"""

import numpy as np

try:
    import objc
    from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory,
                        NSBackingStoreBuffered, NSBitmapImageRep, NSColor,
                        NSImage, NSImageView, NSMenu, NSMenuItem, NSScreen,
                        NSStatusBar, NSVisualEffectView, NSWindow,
                        NSWindowCollectionBehaviorCanJoinAllSpaces,
                        NSWindowCollectionBehaviorStationary,
                        NSWindowStyleMaskBorderless, NSAttributedString,
                        NSFont, NSFontAttributeName,
                        NSForegroundColorAttributeName, NSGraphicsContext,
                        NSKernAttributeName, NSView)
    from Foundation import NSDate, NSMakeRect, NSObject, NSRunLoop
    _APPKIT = True
except Exception:                                    # not macOS, or no pyobjc
    _APPKIT = False
    NSObject = object


def reduce_motion():
    """True when the user has asked macOS to reduce motion. An idle widget
    that breathes forever is exactly the kind of thing that setting is for."""
    if not _APPKIT:
        return False
    try:
        from AppKit import NSWorkspace
        return bool(NSWorkspace.sharedWorkspace()
                    .accessibilityDisplayShouldReduceMotion())
    except Exception:
        return False


_TEXT_CACHE = {}


def text_bitmap(text, px, weight=0.0, tracking=0.0):
    """Real macOS type (SF Pro) rasterised to a straight-alpha WHITE RGBA
    array. OpenCV's Hershey fonts are single-stroke vectors from the 1960s -
    next to system text they look like a plotter drew them.

    Returns None when AppKit is unavailable so callers can fall back."""
    if not _APPKIT or not text:
        return None
    key = (text, round(px, 1), weight, tracking)
    hit = _TEXT_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        font = NSFont.systemFontOfSize_weight_(px, weight)
        attrs = {NSFontAttributeName: font,
                 NSForegroundColorAttributeName: NSColor.whiteColor(),
                 NSKernAttributeName: tracking}
        s = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        sz = s.size()
        w = int(sz.width) + 6
        h = int(sz.height) + 6
        rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None, w, h, 8, 4, True, False, "NSDeviceRGBColorSpace", w * 4, 32)
        ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.setCurrentContext_(ctx)
        s.drawAtPoint_((3, 3))
        NSGraphicsContext.restoreGraphicsState()
        buf = np.frombuffer(memoryview(rep.bitmapData()), np.uint8)
        # NSBitmapImageRep stores rows top-down already - flipping here turns
        # every glyph upside down (verified with an "L").
        img = buf[:h * w * 4].reshape(h, w, 4).copy()
        # un-premultiply to straight alpha, and keep it pure white so the
        # caller can tint it to any grey
        a = img[:, :, 3]
        img[:, :, 0] = img[:, :, 1] = img[:, :, 2] = 255
        img[:, :, 3] = a
        _TEXT_CACHE[key] = img
        return img
    except Exception:
        return None


# The HUD material genuinely samples the desktop behind it. (18 is
# ContentBackground - an opaque panel fill that only LOOKS like a blur;
# measured, it renders identically over a white and a black backdrop.)
HUD_MATERIAL = 13            # NSVisualEffectMaterialHUDWindow
BEHIND_WINDOW = 0            # NSVisualEffectBlendingModeBehindWindow
ACTIVE = 1                   # NSVisualEffectStateActive
STATUS_LEVEL = 25            # above ordinary windows, below the menu bar


if _APPKIT:
    class _DragView(NSView):
        """Lets the user pick the widget up and put it anywhere. The window
        itself is click-through except while the cursor is actually over the
        pill (see GlassPill.update_hit), so this never blocks the desktop."""

        def initWithFrame_(self, f):
            self = objc.super(_DragView, self).initWithFrame_(f)
            if self is None:
                return None
            self._m0 = None
            self._w0 = None
            self._on_drop = None
            return self

        def setOnDrop_(self, cb):
            self._on_drop = cb

        def acceptsFirstMouse_(self, event):
            return True                      # drag on the very first click

        def mouseDown_(self, event):
            from AppKit import NSEvent
            self._m0 = NSEvent.mouseLocation()
            f = self.window().frame()
            self._w0 = (f.origin.x, f.origin.y)

        def mouseDragged_(self, event):
            from AppKit import NSEvent
            if self._m0 is None:
                return
            m = NSEvent.mouseLocation()      # screen coords survive the move
            self.window().setFrameOrigin_(
                (self._w0[0] + m.x - self._m0.x,
                 self._w0[1] + m.y - self._m0.y))

        def mouseUp_(self, event):
            self._m0 = None
            if self._on_drop is not None:
                f = self.window().frame()
                self._on_drop(float(f.origin.x), float(f.origin.y))

    class _MenuTarget(NSObject):
        """Menu clicks land here. A borderless, non-activating window can
        never receive key presses (by design - it must not steal focus from
        the app being controlled), so the menu bar IS the control surface."""

        def initWithHandler_(self, handler):
            self = objc.super(_MenuTarget, self).init()
            if self is None:
                return None
            self._handler = handler
            return self

        def fire_(self, sender):
            self._handler(str(sender.representedObject()))


class GlassPill:
    """A frosted, borderless, always-on-top widget. `ok` is False when the
    platform cannot provide one - callers must fall back to the OpenCV view
    rather than crash."""

    def __init__(self, win_w, win_h, y_from_bottom, menu=(), on_menu=None,
                 on_drop=None, origin=None):
        self.ok = False
        self.win_w, self.win_h = win_w, win_h
        self._hot = []
        self._ignoring = True
        if not _APPKIT:
            return
        try:
            self._build(win_w, win_h, y_from_bottom, menu, on_menu)
            if on_drop is not None:
                self.root.setOnDrop_(on_drop)
            if origin is not None:
                self.set_origin(*origin)
            self.ok = True
        except Exception as e:                       # never take the app down
            print(f"glass widget unavailable ({e}) - using the plain window")

    # ---------------------------------------------------------------- build
    def _build(self, w, h, y, menu, on_menu):
        self.app = NSApplication.sharedApplication()
        self.app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        scr = NSScreen.mainScreen().frame()
        self.screen_w = scr.size.width
        rect = NSMakeRect((scr.size.width - w) / 2, y, w, h)
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        self.win.setOpaque_(False)
        self.win.setBackgroundColor_(NSColor.clearColor())
        self.win.setLevel_(STATUS_LEVEL)
        self.win.setIgnoresMouseEvents_(True)        # never eat a real click
        self.win.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | (1 << 8))                  # fullScreenAuxiliary: stay visible
                                         # over full-screen apps too
        self.win.setHasShadow_(False)                # the pill casts its own

        root = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        root.setMaterial_(HUD_MATERIAL)
        root.setBlendingMode_(BEHIND_WINDOW)
        root.setState_(ACTIVE)
        root.setWantsLayer_(True)
        root.layer().setMasksToBounds_(True)
        # the WINDOW is a big invisible canvas; only this view is frosted, so
        # the pill can grow and shrink without ever resizing the window
        root.layer().setCornerRadius_(h / 2.0)
        root.layer().setShadowOpacity_(0.45)
        root.layer().setShadowRadius_(14.0)
        root.layer().setShadowOffset_((0, -3))
        self.fx = root

        canvas = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, w, h))
        canvas.setBlendingMode_(BEHIND_WINDOW)
        canvas.setState_(ACTIVE)
        canvas.setMaterial_(HUD_MATERIAL)
        self.win.setContentView_(self._clear_container(w, h))
        self.win.contentView().addSubview_(self.fx)

        # a second frosted chip for the hand. Without it the hand floats on
        # bare desktop and vanishes over a light wallpaper.
        chip = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
        chip.setMaterial_(HUD_MATERIAL)
        chip.setBlendingMode_(BEHIND_WINDOW)
        chip.setState_(ACTIVE)
        chip.setWantsLayer_(True)
        chip.layer().setMasksToBounds_(True)
        chip.layer().setCornerRadius_(12.0)
        chip.layer().setShadowOpacity_(0.4)
        chip.layer().setShadowRadius_(12.0)
        chip.setHidden_(True)
        self.chip = chip
        self.win.contentView().addSubview_(chip)

        self.iv = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        self.iv.setImageScaling_(0)                  # NSImageScaleNone: 1:1
        self.win.contentView().addSubview_(self.iv)

        self._menu_item = None
        if menu and on_menu is not None:
            self._build_menu(menu, on_menu)
        self.win.orderFrontRegardless()

    def _clear_container(self, w, h):
        v = _DragView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        v.setWantsLayer_(True)
        self.root = v
        return v

    def _build_menu(self, items, on_menu):
        bar = NSStatusBar.systemStatusBar()
        self._status = bar.statusItemWithLength_(-1.0)   # variable length
        self._status.button().setTitle_("◎")
        self._target = _MenuTarget.alloc().initWithHandler_(on_menu)
        m = NSMenu.alloc().init()
        for title, key in items:
            if title == "-":
                m.addItem_(NSMenuItem.separatorItem())
                continue
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, "fire:", "")
            it.setTarget_(self._target)
            it.setRepresentedObject_(key)
            m.addItem_(it)
        self._status.setMenu_(m)

    # ----------------------------------------------------------------- draw
    def set_pill(self, x, y, w, h):
        """Place the frosted capsule inside the window, in window points with
        the origin at the BOTTOM-left (AppKit's convention)."""
        if not self.ok:
            return
        self.fx.setFrame_(NSMakeRect(x, y, w, h))
        self.fx.layer().setCornerRadius_(h / 2.0)

    def paint(self, rgba, scale=2):
        """rgba: HxWx4 uint8, straight (non-premultiplied) alpha, drawn at
        `scale` device pixels per point."""
        if not self.ok:
            return
        h, w = rgba.shape[:2]
        # AppKit expects premultiplied alpha; skipping this makes every
        # antialiased edge glow.
        a = rgba[:, :, 3:4].astype(np.uint16)
        out = np.empty_like(rgba)
        out[:, :, :3] = (rgba[:, :, :3].astype(np.uint16) * a // 255)
        out[:, :, 3] = rgba[:, :, 3]
        out = np.ascontiguousarray(out)

        rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None, w, h, 8, 4, True, False, "NSDeviceRGBColorSpace", w * 4, 32)
        memoryview(rep.bitmapData())[:] = out.tobytes()
        img = NSImage.alloc().initWithSize_((w / scale, h / scale))
        img.addRepresentation_(rep)
        self.iv.setImage_(img)

    def update_hit(self, rects):
        """Accept the mouse ONLY while the cursor is over the visible widget.
        Anything else would turn the invisible canvas into a dead zone the
        user cannot click through - the widget must never cost them a click.
        `rects` are in window points (AppKit origin, bottom-left)."""
        if not self.ok:
            return
        try:
            from AppKit import NSEvent
            p = NSEvent.mouseLocation()
            f = self.win.frame()
            lx, ly = p.x - f.origin.x, p.y - f.origin.y
            inside = any(x <= lx <= x + w and y <= ly <= y + h
                         for (x, y, w, h) in rects if w > 0 and h > 0)
            if inside == self._ignoring:          # only touch it on a change
                self.win.setIgnoresMouseEvents_(not inside)
                self._ignoring = not inside
        except Exception:
            pass

    def set_origin(self, x, y):
        if self.ok:
            self.win.setFrameOrigin_((float(x), float(y)))

    def origin(self):
        if not self.ok:
            return None
        f = self.win.frame()
        return (float(f.origin.x), float(f.origin.y))

    def move_bottom(self, pos):
        """pos: 'center' or 'right' along the bottom of the screen."""
        if not self.ok:
            return
        f = self.win.frame()
        x = ((self.screen_w - self.win_w) / 2 if pos == "center"
             else self.screen_w - self.win_w - 8)
        self.win.setFrameOrigin_((x, f.origin.y))

    def set_chip(self, rect):
        """The hand's own frosted panel. Pass None to hide it."""
        if not self.ok:
            return
        if rect is None:
            self.chip.setHidden_(True)
            return
        x, y, w, h = rect
        self.chip.setHidden_(False)
        self.chip.setFrame_(NSMakeRect(x, y, max(1, w), max(1, h)))

    def set_visible(self, on):
        if not self.ok:
            return
        if on:
            self.win.orderFrontRegardless()
        else:
            self.win.orderOut_(None)

    def tick(self, seconds=0.0):
        """Let AppKit draw. Called once per camera frame - we never hand the
        main thread over to NSApp.run()."""
        if not self.ok:
            return
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(seconds))

    def close(self):
        if self.ok:
            try:
                self.win.orderOut_(None)
            except Exception:
                pass
