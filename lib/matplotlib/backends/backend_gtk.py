from __future__ import division

import os, sys, math

try:
    import pygtk
    pygtk.require('2.0')
except:
    print sys.exc_info()[1]
    raise SystemExit('PyGTK version 1.99.16 or greater is required to run the GTK/GTKAgg Matplotlib backend')

import gobject
import gtk
version_required = (1,99,16)
if gtk.pygtk_version < version_required:
    raise SystemExit ("PyGTK %d.%d.%d is installed\n"
                      "PyGTK %d.%d.%d or later is required"
                      % (gtk.pygtk_version + version_required))
from gtk import gdk
import pango

import matplotlib
from matplotlib import verbose
from matplotlib.numerix import asarray, fromstring, UInt8, zeros, \
     where, transpose, nonzero, indices, ones, nx

import matplotlib.numerix as numerix
from matplotlib.cbook import is_string_like, enumerate, True, False, onetrue
from matplotlib.font_manager import fontManager

from matplotlib.backend_bases import \
     RendererBase, GraphicsContextBase, FigureManagerBase, FigureCanvasBase,\
     NavigationToolbar2, cursors, MplEvent
from matplotlib._matlab_helpers import Gcf
from matplotlib.figure import Figure

try: from matplotlib.mathtext import math_parse_s_ft2font
except ImportError:
    print >>sys.stderr, 'backend_gtk could not import mathtext (build with ft2font)'
    useMathText = False
else: useMathText = True

# the true dots per inch on the screen; should be display dependent
# see http://groups.google.com/groups?q=screen+dpi+x11&hl=en&lr=&ie=UTF-8&oe=UTF-8&safe=off&selm=7077.26e81ad5%40swift.cs.tcd.ie&rnum=5 for some info about screen dpi
PIXELS_PER_INCH = 96

backend_version = 'unknown'
cursord = {
    cursors.MOVE          : gtk.gdk.Cursor(gtk.gdk.FLEUR),
    cursors.HAND          : gtk.gdk.Cursor(gtk.gdk.HAND2),
    cursors.POINTER       : gtk.gdk.Cursor(gtk.gdk.LEFT_PTR),
    cursors.SELECT_REGION : gtk.gdk.Cursor(gtk.gdk.TCROSS),
    }

class ColorManagerGTK:
    _cached = {}  # a map from get_color args to colors
    _cmap = None
    
    def set_drawing_area(self, da):
        self._cmap = da.get_colormap()

    def get_color(self, rgb):
        """
        RGB is a unit RGB tuple, return a gtk.gdk.Color
        """

        try: return self._cached[tuple(rgb)]
        except KeyError: pass
        
        if self._cmap is None:
            raise RuntimeError('First set the drawing area!')

        #print 'rgb is', rgb
        r,g,b = rgb
        color = self._cmap.alloc_color(int(r*65025),int(g*65025),int(b*65025))
        self._cached[tuple(rgb)] = color
        return color

    def get_rgb(self, color):
        """
        RGB is a unit RGB tuple, return a gtk.gdk.Color
        """

        return [val/65535 for val in (color.red, color.green, color.blue)]

colorManager = ColorManagerGTK()

class RendererGTK(RendererBase):

    fontweights = {
        100          : pango.WEIGHT_ULTRALIGHT,
        200          : pango.WEIGHT_LIGHT,
        300          : pango.WEIGHT_LIGHT,
        400          : pango.WEIGHT_NORMAL,
        500          : pango.WEIGHT_NORMAL,
        600          : pango.WEIGHT_BOLD,
        700          : pango.WEIGHT_BOLD,
        800          : pango.WEIGHT_HEAVY,
        900          : pango.WEIGHT_ULTRABOLD,
        'ultralight' : pango.WEIGHT_ULTRALIGHT,
        'light'      : pango.WEIGHT_LIGHT,
        'normal'     : pango.WEIGHT_NORMAL,
        'medium'     : pango.WEIGHT_NORMAL,
        'semibold'   : pango.WEIGHT_BOLD,
        'bold'       : pango.WEIGHT_BOLD,
        'heavy'      : pango.WEIGHT_HEAVY,
        'ultrabold'  : pango.WEIGHT_ULTRABOLD,
        'black'      : pango.WEIGHT_ULTRABOLD,
                   }
    fontangles = {
        'italic'  : pango.STYLE_ITALIC,
        'normal'  : pango.STYLE_NORMAL,
        'oblique' : pango.STYLE_OBLIQUE,
        }

    # cache for efficiency, these must be at class, not instance level
    layoutd = {}  # a map from text prop tups to pango layouts
    extentd = {}  # a map from text prop tups to text extents
    offsetd = {}  # a map from text prop tups to text offsets
    rotated = {}  # a map from text prop tups to rotated text pixbufs

    def __init__(self, gtkDA, gdkDrawable, dpi):
        self.gtkDA = gtkDA
        self.gdkDrawable = gdkDrawable
        self.width, self.height = self.gdkDrawable.get_size()
        self.dpi = dpi

    def flipy(self):
        return True

    def offset_text_height(self):
        return True

    def get_text_width_height(self, s, prop, ismath):
        """
        get the width and height in display coords of the string s
        with FontPropertry prop
        """
        if ismath:
            width, height, fonts = math_parse_s_ft2font(
                s, self.dpi.get(), prop.get_size_in_points())
            return width, height

        layout = self.get_pango_layout(s, prop)
        inkRect, logicalRect = layout.get_pixel_extents()
        rect = inkRect
        #rect = logicalRect
        l, b, w, h = rect
        return w, h+1

    def get_canvas_width_height(self):
        'return the canvas width and height in display coords'
        return self.width, self.height

    
    def draw_arc(self, gc, rgbFace, x, y, width, height, angle1, angle2):
        """
        Draw an arc centered at x,y with width and height
        """
        x, y = int(x-0.5*width), self.height-int(y+0.5*height)
        w, h = int(width)+1, int(height)+1
        a1, a2 = int(angle1*64), int(angle2*64)
        
        if rgbFace is not None:
            edgecolor = gc.gdkGC.foreground
            facecolor = colorManager.get_color(rgbFace)
            gc.gdkGC.foreground = facecolor
            self.gdkDrawable.draw_arc(gc.gdkGC, True, x, y, w, h, a1, a2)
            gc.gdkGC.foreground = edgecolor
        self.gdkDrawable.draw_arc(gc.gdkGC, False, x, y, w, h, a1, a2)

    def draw_image(self, x, y, im, origin, bbox):
        """
        Draw the Image instance into the current axes; x is the
        distance in pixels from the left hand side of the canvas. y is
        the distance from the origin.  That is, if origin is upper, y
        is the distance from top.  If origin is lower, y is the
        distance from bottom
        """
        #print 'draw_image'

        if bbox is not None:
            l,b,w,h = bbox.get_bounds()
            #rectangle = (int(l), self.height-int(b+h),
            #             int(w), int(h))
            # set clip rect?

        flipud = origin=='lower'
        rows, cols, s = im.as_str(flipud)

        X = fromstring(s, UInt8)
        X.shape = rows, cols, 4

        pb=gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB,
                          has_alpha=1, bits_per_sample=8,
                          width=cols, height=rows)
        try:
            pa = pb.get_pixels_array()
        except AttributeError:
            pa = pb.pixel_array
        except RuntimeError, exc: #  pygtk was not compiled with Numeric Python support
            print >>sys.stderr, 'Error:', exc
            return

        pa[:,:,:] = X

        gc = self.new_gc()

        if flipud:  y = self.height-y-rows

        pb.render_to_drawable(self.gdkDrawable, gc.gdkGC, 0, 0,
                              int(x), int(y), cols, rows,
                              gdk.RGB_DITHER_NONE, 0, 0)

            
    def draw_line(self, gc, x1, y1, x2, y2):
        """
        Draw a single line from x1,y1 to x2,y2
        """
        self.gdkDrawable.draw_line(
            gc.gdkGC, int(x1), self.height-int(y1),
            int(x2), self.height-int(y2))


    def draw_lines(self, gc, x, y):
        x = x.astype(nx.Int16)
        y = self.height*ones(y.shape, nx.Int16) - y.astype(nx.Int16)  

        self.gdkDrawable.draw_lines(gc.gdkGC, zip(x,y))

    def draw_point(self, gc, x, y):
        """
        Draw a single point at x,y
        """
        self.gdkDrawable.draw_point(
            gc.gdkGC, int(x), self.height-int(y))

    def draw_polygon(self, gc, rgbFace, points):
        """
        Draw a polygon.  points is a len vertices tuple, each element
        giving the x,y coords a vertex

        If gcFace is not None, fill the rectangle with it.  gcEdge
        is a GraphicsContext instance

        """
        points = [(int(x), self.height-int(y)) for x,y in points]
        if rgbFace is not None:
            edgecolor = gc.gdkGC.foreground
            facecolor = colorManager.get_color(rgbFace)
            gc.gdkGC.foreground = facecolor
            self.gdkDrawable.draw_polygon(gc.gdkGC, True, points)
            gc.gdkGC.foreground = edgecolor

        self.gdkDrawable.draw_polygon(gc.gdkGC, False, points)


    def draw_rectangle(self, gc, rgbFace, x, y, width, height):
        """
        Draw a rectangle at lower left x,y with width and height
        If filled=True, fill the rectangle with the gc foreground
        gc is a GraphicsContext instance
        """
        x, y = int(x), self.height-int(y+height)
        #x, y = int(x), self.height-int(math.ceil(y+height))
        w, h = int(math.ceil(width)), int(math.ceil(height))


        if rgbFace is not None:
            edgecolor = gc.gdkGC.foreground
            facecolor = colorManager.get_color(rgbFace)
            gc.gdkGC.foreground = facecolor
            self.gdkDrawable.draw_rectangle(gc.gdkGC, True, x, y, w, h)
            gc.gdkGC.foreground = edgecolor
            
        self.gdkDrawable.draw_rectangle(gc.gdkGC, False, x, y, w, h)


    #def _draw_rotated_text(self, gc, x, y, s, prop, angle, ismath): # ismath is not used
    def _draw_rotated_text(self, gc, x, y, s, prop, angle): # ismath is not used
        """
        Draw the text rotated 90 degrees
        """

        gdrawable = self.gdkDrawable
        ggc = gc.gdkGC

        layout = self.get_pango_layout(s, prop)
        inkRect, logicalRect = layout.get_pixel_extents()
        rect = inkRect
        l, b, w, h = rect

        x = int(x-h)
        y = int(y-w)
        # get the background image

        # todo: cache rotation for dynamic redraw until pygtk mem leak
        # fixed
        key = (x,y,s,angle,hash(prop))
        imageOut = self.rotated.get(key)
        if imageOut is not None:
            gdrawable.draw_image(ggc, imageOut, 0, 0, x, y, h, w)
            return

        # save the background
        imageBack = gdrawable.get_image(x, y, w, h)
        imageVert = gdrawable.get_image(x, y, h, w)

        # transform the vertical image, write it onto the renderer,
        # and draw the layout onto it
        imageFlip = gtk.gdk.Image(type=gdk.IMAGE_NORMAL,
                                  visual=gdrawable.get_visual(),
                                  width=w, height=h)
        if imageFlip is None or imageBack is None or imageVert is None:
            print >> sys.stderr, "Could not renderer vertical text", s
            return
        imageFlip.set_colormap(gdrawable.get_colormap())
        for i in range(w):
            for j in range(h):
                imageFlip.put_pixel(i, j, imageVert.get_pixel(j,w-i-1) )

        gdrawable.draw_image(ggc, imageFlip, 0, 0, x, y, w, h)
        gdrawable.draw_layout(ggc, x, y-b, layout)

        # now get that image and flip it vertical
        imageIn = gdrawable.get_image(x, y, w, h)
        imageOut = gtk.gdk.Image(type=gdk.IMAGE_NORMAL,
                                 visual=gdrawable.get_visual(),
                                 width=h, height=w)
        imageOut.set_colormap(gdrawable.get_colormap())
        for i in range(w):
            for j in range(h):
                imageOut.put_pixel(j, i, imageIn.get_pixel(w-i-1,j) )

        # draw the old background and the flipped text
        gdrawable.draw_image(ggc, imageBack, 0, 0, x, y, w, h)
        gdrawable.draw_image(ggc, imageOut, 0, 0, x, y, h, w)
        self.rotated[key] = imageOut
        return True


    def draw_mathtext(self, gc, x, y, s, prop, angle):

        size = prop.get_size_in_points()
        width, height, fonts = math_parse_s_ft2font(
            s, self.dpi.get(), size)

        if angle==90:
            width, height = height, width
        x = int(x)
        y = int(y)
        
        rgb = gc.get_rgb()
        #rgba = (rgb[0], rgb[1], rgb[2], gc.get_alpha())

        imw, imh, s = fonts[0].image_as_str()
        N = imw*imh

        # a numpixels by num fonts array
        Xall = zeros((N,len(fonts)), typecode=UInt8)

        for i, font in enumerate(fonts):
            if angle == 90:
                font.horiz_image_to_vert_image() # <-- Rotate
            imw, imh, s = font.image_as_str()
            Xall[:,i] = fromstring(s, UInt8)  

        # get the max alpha at each pixel
        Xs = numerix.max(Xall,1)

        # convert it to it's proper shape

        Xs.shape = imh, imw
                

        pb=gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB,
                          has_alpha=1, bits_per_sample=8, width=imw, height=imh)

        try:
            pa = pb.get_pixels_array()
        except AttributeError:
            pa = pb.pixel_array
        except RuntimeError, exc: #  pygtk was not compiled with Numeric Python support
            print >>sys.stderr, 'Error:', exc
            return        

        pa[:,:,0]=int(rgb[0]*255)
        pa[:,:,1]=int(rgb[1]*255)
        pa[:,:,2]=int(rgb[2]*255)
        pa[:,:,3]=Xs


        if angle==90:
            x -= width
        y -= height
        pb.render_to_drawable(self.gdkDrawable, gc.gdkGC, 0, 0,
                              int(x), int(y), imw, imh,
                              gdk.RGB_DITHER_NONE, 0, 0)
            
        
    def draw_text(self, gc, x, y, s, prop, angle, ismath):
        
        if ismath:
            self.draw_mathtext(gc, x, y, s, prop, angle)
            return

        w, h = self.get_text_width_height(s, prop, ismath)
        x = int(x)
        y = int(y)

        if angle==90:
            #self._draw_rotated_text(gc, x, y, s, prop, angle, ismath)
            self._draw_rotated_text(gc, x, y, s, prop, angle)
            return

        layout = self.get_pango_layout(s, prop)
        inkRect, logicalRect = layout.get_pixel_extents()
        rect = inkRect
        l, b, w, h = rect

        self.gdkDrawable.draw_layout(gc.gdkGC, x=x, y=y-h-b,
                                     layout=layout)

        
    def get_pango_layout(self, s, prop):
        """
        Return a pango layout instance for Text instance t.  cache to
        layoutd
        """

        key = self.dpi.get(), s, hash(prop)
        layout = self.layoutd.get(key)
        if layout is not None:
            return layout

        fontname = prop.get_name()
        #if fontname.lower()=='times': fontname = "serif"
        
        font = pango.FontDescription('%s' % fontname)
        
        font.set_weight(self.fontweights[prop.get_weight()])
        font.set_style(self.fontangles[prop.get_style()])

        scale = self.get_text_scale()
        size  = prop.get_size_in_points()
        font.set_size(int(scale*size*1024))
        #context = self.gtkDA.create_pango_context() # not used
        layout  = self.gtkDA.create_pango_layout(s)
        layout.set_font_description(font)    

        self.layoutd[key] = layout
        return layout


    def get_text_scale(self):
        """
        Return the scale factor for fontsize taking screendpi and pixels per
        inch into account
        """
        return self.dpi.get()/PIXELS_PER_INCH
        #return self.dpi.get()/72.0

    def new_gc(self):
        return GraphicsContextGTK(self.gdkDrawable.new_gc(), self)

    def points_to_pixels(self, points):
        """
        convert point measures to pixels using dpi and the pixels per
        inch of the display
        """
        # should return int(round(points...)) ? - saves calling fn doing the work
        return points*(PIXELS_PER_INCH/72.0*self.dpi.get()/72.0)
        #return points*(self.dpi.get()/72.0)


class GraphicsContextGTK(GraphicsContextBase):

    _joind = {
        'bevel' : gdk.JOIN_BEVEL,
        'miter' : gdk.JOIN_MITER,
        'round' : gdk.JOIN_ROUND,
        }

    _capd = {
        'butt' : gdk.CAP_BUTT,
        'projecting' : gdk.CAP_PROJECTING,
        'round' : gdk.CAP_ROUND,
        }

              
    def __init__(self, gdkGC, renderer):
            GraphicsContextBase.__init__(self)
            self.gdkGC = gdkGC
            self.renderer = renderer


    def set_clip_rectangle(self, rectangle):
        GraphicsContextBase.set_clip_rectangle(self, rectangle)
        l,b,w,h = rectangle
        rectangle = (int(l), self.renderer.height-int(b+h)+1,
                     int(w), int(h))
        #rectangle = (int(l), self.renderer.height-int(b+h),
        #             int(w+1), int(h+2))
        self.gdkGC.set_clip_rectangle(rectangle)        


    def set_dashes(self, dash_offset, dash_list):
        GraphicsContextBase.set_dashes(self, dash_offset, dash_list)

        if dash_list is not None:
            pixels = self.renderer.points_to_pixels(asarray(dash_list))
            dl = [max(1, int(round(val))) for val in pixels]
            self.gdkGC.set_dashes(dash_offset, dl)
            self.gdkGC.line_style = gdk.LINE_ON_OFF_DASH
        else:
            self.gdkGC.line_style = gdk.LINE_SOLID

    def set_foreground(self, fg, isRGB=None):
        """
        Set the foreground color.  fg can be a matlab format string, a
        html hex color string, an rgb unit tuple, or a float between 0
        and 1.  In the latter case, grayscale is used.
        """
        GraphicsContextBase.set_foreground(self, fg, isRGB)
        self.gdkGC.foreground = self._get_gdk_color()

    def set_graylevel(self, frac):
        """
        Set the foreground color to be a gray level with frac frac
        """
        GraphicsContextBase.set_graylevel(self, frac)
        self.gdkGC.foreground = self._get_gdk_color()
        

    def set_linewidth(self, lw):
        GraphicsContextBase.set_linewidth(self, lw)

        pixels = self.renderer.points_to_pixels(lw)
        self.gdkGC.line_width = max(1, int(round(pixels)))

    def set_linestyle(self, style):
        GraphicsContextBase.set_linestyle(self, style)
                                               
    def set_capstyle(self, cs):
        """
        Set the capstyle as a string in ('butt', 'round', 'projecting')
        """
        GraphicsContextBase.set_capstyle(self, cs)
        self.gdkGC.cap_style = self._capd[self._capstyle]

    def set_joinstyle(self, js):
        """
        Set the join style to be one of ('miter', 'round', 'bevel')
        """
        GraphicsContextBase.set_joinstyle(self, js)
        self.gdkGC.join_style = self._joind[self._joinstyle]

    def _get_gdk_color(self):
        return colorManager.get_color(self.get_rgb())


def raise_msg_to_str(msg):
    """msg is a return arg from a raise.  Join with new lines"""
    if not is_string_like(msg):
        msg = '\n'.join(map(str, msg))
    return msg
    

def error_msg_gtk(msg, parent=None):
    dialog = gtk.MessageDialog(
        parent         = parent,
        type           = gtk.MESSAGE_ERROR,
        buttons        = gtk.BUTTONS_OK,
        message_format = msg)
    dialog.run()
    dialog.destroy()


def draw_if_interactive():

    if matplotlib.is_interactive():
        figManager =  Gcf.get_active()
        if figManager is not None:
            figManager.canvas.draw()

def show(mainloop=True):
    """
    Show all the figures and enter the gtk mainloop

    This should be the last line of your script
    """

    for manager in Gcf.get_all_fig_managers():
        manager.window.show()
        
    if show._needmain and mainloop:
        if gtk.pygtk_version >= (2,3,97):  gtk.main()
        else:                              gtk.mainloop()
        show._needmain = False
show._needmain = True

def _quit_after_print_xvfb(*args):

    for manager in Gcf.get_all_fig_managers():
        if len(manager.canvas._printQued): break
    else:
        gtk.main_quit()
    

def show_xvfb():
    """
    Print the pending figures only then quit, no screen draw
    """
    for manager in Gcf.get_all_fig_managers():
        manager.canvas.set_do_plot(False)
        manager.window.show()
        
    gtk.idle_add(_quit_after_print_xvfb)
    if gtk.pygtk_version >= (2,3,97):
        gtk.main()
    else:
        gtk.mainloop()


def new_figure_manager(num, *args, **kwargs):
    """
    Create a new figure manager instance
    """
    figure = Figure(*args, **kwargs)

    canvas = FigureCanvasGTK(figure)
    return FigureManagerGTK(canvas, num)


class FigureCanvasGTK(gtk.DrawingArea, FigureCanvasBase):
    keyvald = {65507 : 'control',
               65505 : 'shift',
               65513 : 'alt',
               65508 : 'control',
               65506 : 'shift',
               65514 : 'alt',
               }


    def __init__(self, figure):
        FigureCanvasBase.__init__(self, figure)
        gtk.DrawingArea.__init__(self)
        
        self.set_flags(gtk.CAN_FOCUS)
        self.grab_focus()
        # self.pixmap_width, self.pixmap_height = -1, -1 
        self._isRealized = False
        self._gpixmap    = None
        self._doplot     = True
        self._printQued  = []
        self._idleID     = 0    # used in gtkagg
        self._new_pixmap = True

        self._button = None  # the button pressed
        self._key = None     # the key pressed
        w = figure.bbox.width()
        h = figure.bbox.height()
        self.set_size_request(int(w), int(h))
        self.set_double_buffered(False)
        
        self.connect('key_press_event', self.key_press_event)
        self.connect('key_release_event', self.key_release_event)
        self.connect('expose_event', self.expose_event)
        self.connect('configure_event', self.configure_event)
        self.connect('realize', self.realize)
        self.connect('motion_notify_event', self.motion_notify_event)
        self.connect('button_press_event', self.button_press_event)
        self.connect('button_release_event', self.button_release_event)

        self.set_events(
            #gdk.FOCUS_CHANGE_MASK|
            gdk.KEY_PRESS_MASK|
            gdk.KEY_RELEASE_MASK|
            gdk.EXPOSURE_MASK |
            gdk.LEAVE_NOTIFY_MASK |
            gdk.BUTTON_PRESS_MASK |
            gdk.BUTTON_RELEASE_MASK |
            gdk.POINTER_MOTION_MASK )

        self._lastCursor = None
        colorManager.set_drawing_area(self)


    def button_press_event(self, widget, event):
        self._button = event.button

    def button_release_event(self, widget, event):
        self._button = None

    def motion_notify_event(self, widget, event):
        #print 'backend_gtk', event.x, event.y
        pass
    
    def key_press_event(self, widget, event):

        if self.keyvald.has_key(event.keyval):
            key = self.keyvald[event.keyval]
        elif event.keyval <256:
            key = chr(event.keyval)
        else:
            key = None
            
        ctrl  = event.state & gtk.gdk.CONTROL_MASK
        shift = event.state & gtk.gdk.SHIFT_MASK
        
        self._key = key

    def key_release_event(self, widget, event):        
        self._key = None
        
    def mpl_connect(self, s, func):
        
        if s not in self.events:
            error_msg('Can only connect events of type "%s"\nDo not know how to handle "%s"' %(', '.join(self.events), s))    
            

        def wrapper(widget, event):
            thisEvent = MplEvent(s, self) 

            thisEvent.x = event.x
            # flipy so y=0 is bottom of canvas
            thisEvent.y = self.figure.bbox.height() - event.y
 
            thisEvent.button = self._button
            thisEvent.key = self._key

            thisEvent.inaxes = None
            for a in self.figure.get_axes():
                if a.in_axes(thisEvent.x, thisEvent.y):
                    thisEvent.inaxes = a
                    xdata, ydata = a.transData.inverse_xy_tup((thisEvent.x, thisEvent.y))
                    thisEvent.xdata  = xdata
                    thisEvent.ydata  = ydata
                    break
                
            
            func(thisEvent)
            return False  # return True blocks other connects
        cid =  self.connect(s, wrapper)
        return cid

    def mpl_disconnect(self, cid):
        self.disconnect(cid)
        return None

    def realize(self, widget):
        self._ggc = self.window.new_gc()
        self._isRealized = True
        for fname, dpi, facecolor, edgecolor in self._printQued:
            self.print_figure(fname, dpi, facecolor, edgecolor)
        self._printQued = []
        return True


    def configure_event(self, widget, event):
        if widget.window is None: return 

        w,h = widget.window.get_size()
        if w==1 or h==1: return # empty fig

        # compute desired figure size in inches
        dpival = self.figure.dpi.get()
        winch = w/dpival
        hinch = h/dpival
        self.figure.set_figsize_inches(winch, hinch)
        
        self._new_pixmap = True
        return True
        

    def draw(self):
        if self._doplot:
            self._new_pixmap = True
            self.expose_event(self, None)


    def expose_event(self, widget, event):
        if self.window is None: return 

        if self._new_pixmap: # create new pixmap
            width  = int(self.figure.bbox.width())
            height = int(self.figure.bbox.height())

            self._gpixmap = gtk.gdk.Pixmap(self.window, width, height)
            self.figure.draw(RendererGTK(self, self._gpixmap, self.figure.dpi))
            self.window.draw_drawable(self._ggc, self._gpixmap,
                                      0, 0, 0, 0, width, height)
        else:                # draw from existing pixmap
            r = event.area
            self.window.draw_drawable(self._ggc, self._gpixmap,
                                      r.x, r.y, r.x, r.y, r.width, r.height)
        self._new_pixmap = False
        return True

#    def _draw_new(self):
#        if width > self.pixmap_width or height > self.pixmap_height:
#            self._gpixmap = gtk.gdk.Pixmap(drawable, width, height)
#            self.pixmap_width  = width
#            self.pixmap_height = height


    def print_figure(self, filename, dpi=150, facecolor='w', edgecolor='w'):
        # orientation='portrait'):

        if is_string_like(filename): isFileName = True
        else: isFileName = False

        if isFileName:
            root, ext = os.path.splitext(filename)        
            ext = ext.lower()[1:]
            if not len(ext):
                filename = filename + '.png'
                ext = 'png'

            if ext=='png': ftype = 'png'
            elif ext in ('jpg', 'jpeg'): ftype = 'jpeg'
            elif ext.find('ps')>=0: pass
            else:
                error_msg_gtk('Can only save to formats PNG, JPEG, PS or EPS')            
                return
        else: ftype='png'
        
        if not self._isRealized:
            self._printQued.append((filename, dpi, facecolor, edgecolor))
            return

        if isFileName and ext.find('ps')>=0:
            # enable ps save from gtk backend do the import here so we
            # don't have to import afm unless necessary
            from backend_ps import FigureCanvasPS

            origDPI = self.figure.dpi.get()
            ps = self.switch_backends(FigureCanvasPS)
            ps.figure.dpi.set(72)
            ps.print_figure(filename, 72, facecolor, edgecolor)
            self.figure.dpi.set(origDPI)
            return
        elif ext.find('svg')>=0:
            # enable svg save from WX backend only import this if we
            # need it since it parse afm files on import
            from backend_svg import FigureCanvasSVG
            origDPI = self.figure.dpi.get()
            svg = self.switch_backends(FigureCanvasSVG)
            svg.figure.dpi.set(72)
            svg.print_figure(filename, 72, facecolor, edgecolor)
            self.figure.dpi.set(origDPI)                        
            return

        origDPI = self.figure.dpi.get()
        origfacecolor = self.figure.get_facecolor()
        origedgecolor = self.figure.get_edgecolor()

        self.figure.dpi.set(dpi)        
        self.figure.set_facecolor(facecolor)
        self.figure.set_edgecolor(edgecolor)

        l,b,width, height = self.figure.bbox.get_bounds()

        width     = int(width)
        height    = int(height)
        gdrawable = self.window
        gpixmap   = gtk.gdk.Pixmap(gdrawable, width, height)
        pixmap    = RendererGTK(self, gpixmap, self.figure.dpi)

        self.figure.draw(pixmap)  # ? just create pixmap, don't need to draw to screen
        
        pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, 0, 8, width, height)
        pixbuf.get_from_drawable(gpixmap, gdrawable.get_colormap(),
                                 0, 0, 0, 0, width, height)
        
        self.figure.set_facecolor(origfacecolor)
        self.figure.set_edgecolor(origedgecolor)
        self.figure.dpi.set(origDPI)

        self.configure_event(self, 'configure') # why?
            
        try: pixbuf.save(filename, ftype)
        except gobject.GError, msg:
            msg = raise_msg_to_str(msg)
            # note the error must be displayed here because trapping
            # the error on a call or print_figure may not work because
            # printing can be qued and called from realize
            if isFileName:
                error_msg_gtk('Could not save figure to %s\n\n%s' % (
                    filename, msg))
            else:
                error_msg_gtk('Could not save figure\n%s' % msg)
                
    def set_do_plot(self, b):
        'True if you want to render to screen, False is hardcopy only'
        self._doplot = b


class FigureManagerGTK(FigureManagerBase):
    """
    Public attributes

    canvas      : The FigureCanvas instance
    num         : The Figure number
    toolbar     : The gtk.Toolbar
    window      : The gtk.Window
    
    """
    def __init__(self, canvas, num):
        FigureManagerBase.__init__(self, canvas, num)
        

        self.window = gtk.Window()
        self.window.set_title("Figure %d" % num)
        #self.window.set_border_width(5)

        vbox = gtk.VBox(spacing=3)
        self.window.add(vbox)
        vbox.show()

        self.canvas.show()
        vbox.pack_start(self.canvas, True, True)

        # must be inited after the window, drawingArea and figure
        # attrs are set
        if matplotlib.rcParams['toolbar']=='classic':
            self.toolbar = NavigationToolbar( canvas, self.window )
        elif matplotlib.rcParams['toolbar']=='toolbar2':
            self.toolbar = NavigationToolbar2GTK( canvas )            

        else:
            self.toolbar = None

        if self.toolbar is not None:
            self.toolbar.show()
            vbox.pack_end(self.toolbar, False, False)

        def destroy(*args): Gcf.destroy(num)
        self.window.connect("destroy", destroy)

        if matplotlib.is_interactive():
            self.window.show()


    def add_subplot(self, *args, **kwargs):
        a = FigureManagerBase.add_subplot(self, *args, **kwargs)
        if self.toolbar is not None: self.toolbar.update()
        return a
    
    def add_axes(self, rect, **kwargs):
        a = FigureManagerBase.add_axes(self, rect, **kwargs)
        if self.toolbar is not None: self.toolbar.update()
        return a
    
    def destroy(self, *args):
        self.window.destroy()
        if Gcf.get_num_fig_managers()==0 and not matplotlib.is_interactive():
            gtk.main_quit()

        
class Dialog_MeasureTool(gtk.Dialog):
    def __init__(self):
        gtk.Dialog.__init__(self)
        self.set_title("Axis measurement tool")
        self.vbox.set_spacing(1)
        tooltips = gtk.Tooltips()

        self.posFmt =   'Position: x=%1.4f y=%1.4f'
        self.deltaFmt = 'Delta   : x=%1.4f y=%1.4f'

        self.positionLabel = gtk.Label(self.posFmt % (0,0))
        self.vbox.pack_start(self.positionLabel)
        self.positionLabel.show()
        tooltips.set_tip(self.positionLabel,
                         "Move the mouse to data point over axis")

        self.deltaLabel = gtk.Label(self.deltaFmt % (0,0))
        self.vbox.pack_start(self.deltaLabel)
        self.deltaLabel.show()

        tip = "Left click and hold while dragging mouse to measure " + \
              "delta x and delta y"
        tooltips.set_tip(self.deltaLabel, tip)
                         
        self.show()

    def update_position(self, x, y):
        self.positionLabel.set_text(self.posFmt % (x,y))

    def update_delta(self, dx, dy):
        self.deltaLabel.set_text(self.deltaFmt % (dx,dy))


class NavigationToolbar2GTK(NavigationToolbar2, gtk.Toolbar):
    # list of toolitems to add to the toolbar, format is:
    # text, tooltip_text, image_file, callback(str)
    toolitems = (
        ('Home', 'Reset original view', 'home.png', 'home'),
        ('Back', 'Back to  previous view','back.png', 'back'),
        ('Forward', 'Forward to next view','forward.png', 'forward'),
        ('Pan', 'Pan axes with left mouse, zoom with right', 'move.png','pan'),
        ('Zoom', 'Zoom to rectangle','zoom_to_rect.png', 'zoom'),
        (None, None, None, None),
        ('Save', 'Save the figure','filesave.png', 'save_figure'),
        )
        
    def __init__(self, canvas, *args):
        gtk.Toolbar.__init__(self)
        NavigationToolbar2.__init__(self, canvas)
        self._idleId = 0

    def set_message(self, s):
        if self._idleId==0: self.message.set_label(s)

        
    def set_cursor(self, cursor):
        self.canvas.window.set_cursor(cursord[cursor])

    def release(self, event):
        try: self._imageBack
        except AttributeError: pass
        else: del self._imageBack

    def dynamic_update(self):
        def idle_draw(*args):
            self.canvas.draw()
            self._idleId = 0
            return False
        if self._idleId==0:
            self._idleId = gtk.idle_add(idle_draw)
        
    def draw_rubberband(self, event, x0, y0, x1, y1):
        'adapted from http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/189744'
        drawable = self.canvas.window
        if drawable is None: return

        gc = drawable.new_gc()

        height = self.canvas.figure.bbox.height()
        y1 = height - y1
        y0 = height - y0
        
        w = abs(x1 - x0)
        h = abs(y1 - y0)

        rect = [int(val)for val in min(x0,x1), min(y0, y1), w, h]
        try: lastrect, imageBack = self._imageBack
        except AttributeError:
            #snap image back        
            if event.inaxes is None: return

            ax = event.inaxes
            l,b,w,h = [int(val) for val in ax.bbox.get_bounds()]
            b = y = int(height)-(b+h)
            axrect = l,b,w,h
            self._imageBack = axrect, drawable.get_image(*axrect)            
            drawable.draw_rectangle(gc, False, *rect)
            self._idleId = 0
        else:
            def idle_draw(*args):

                drawable.draw_image(gc, imageBack, 0, 0, *lastrect)
                drawable.draw_rectangle(gc, False, *rect)
                self._idleId = 0
                return False
            if self._idleId==0:
                self._idleId = gtk.idle_add(idle_draw)
        

    def _init_toolbar(self):
        self.set_style(gtk.TOOLBAR_ICONS)

        if gtk.pygtk_version >= (2,3,97):
            self._init_toolbar2_4()
        else:
            self._init_toolbar2_2()


    def _init_toolbar2_2(self):
        basedir = matplotlib.rcParams['datapath']

        for text, tooltip_text, image_file, callback in self.toolitems:
            if text is None:
                 self.append_space()
                 continue
            
            fname = os.path.join(basedir, image_file)
            image = gtk.Image()
            image.set_from_file(fname)
            w = self.append_item(text,
                                 tooltip_text,
                                 'Private',
                                 image,
                                 getattr(self, callback)
                                 )

        self.append_space()

        self.message = gtk.Label()
        self.append_widget(self.message, None, None)
        self.message.show()

        self.fileselect = FileSelection(path=None,
                                        title='Save the figure')

        
        
    def _init_toolbar2_4(self):
        basedir = matplotlib.rcParams['datapath']
        self.tooltips = gtk.Tooltips()

        for text, tooltip_text, image_file, callback in self.toolitems:
            if text is None:
                self.insert( gtk.SeparatorToolItem(), -1 )
                continue
            fname = os.path.join(basedir, image_file)
            image = gtk.Image()
            image.set_from_file(fname)
            tbutton = gtk.ToolButton(image, text)
            self.insert(tbutton, -1)
            tbutton.connect('clicked', getattr(self, callback))
            tbutton.set_tooltip(self.tooltips, tooltip_text, 'Private')

        toolitem = gtk.SeparatorToolItem()
        self.insert(toolitem, -1)
        toolitem.set_draw(False)  # set_draw() not making separator invisible, bug #143692 fixed Jun 06 2004, will be in GTK+ 2.6
        toolitem.set_expand(True)

        toolitem = gtk.ToolItem()
        self.insert(toolitem, -1)
        self.message = gtk.Label()
        toolitem.add(self.message)

        self.show_all()

        self.fileselect = FileChooserDialog(title='Save the figure',
                                            parent=None) # later - add parent
        
    
    def save_figure(self, button):
        fname = self.fileselect.get_filename_from_user()
        if fname:
            try: self.canvas.print_figure(fname)
            except IOError, msg:
                error_msg_gtk('Failed to save %s: Error msg was\n\n%s' % (
                    fname, '\n'.join(map(str, msg))))
                
            
class NavigationToolbar(gtk.Toolbar):
    """
    Public attributes

      canvas - the FigureCanvas  (gtk.DrawingArea)
      win    - the gtk.Window

    """
    # list of toolitems to add to the toolbar, format is:
    # text, tooltip_text, image, callback(str), callback_arg, scroll(bool)
    toolitems = (
        ('Left', 'Pan left with click or wheel mouse (bidirectional)',
         gtk.STOCK_GO_BACK, 'panx', -1, True),
        ('Right', 'Pan right with click or wheel mouse (bidirectional)',
         gtk.STOCK_GO_FORWARD, 'panx', 1, True),
        ('Zoom In X', 'Zoom In X (shrink the x axis limits) with click or wheel' 
         ' mouse (bidirectional)',
         gtk.STOCK_ZOOM_IN, 'zoomx', 1, True),
        ('Zoom Out X', 'Zoom Out X (expand the x axis limits) with click or wheel'
         ' mouse (bidirectional)',
         gtk.STOCK_ZOOM_OUT, 'zoomx', -1, True),
        (None, None, None, None, None, None,),   
        ('Up', 'Pan up with click or wheel mouse (bidirectional)',
         gtk.STOCK_GO_UP, 'pany', 1, True),
        ('Down', 'Pan down with click or wheel mouse (bidirectional)',
         gtk.STOCK_GO_DOWN, 'pany', -1, True),
        ('Zoom In Y', 'Zoom in Y (shrink the y axis limits) with click or wheel'
         ' mouse (bidirectional)',
         gtk.STOCK_ZOOM_IN, 'zoomy', 1, True),
        ('Zoom Out Y', 'Zoom Out Y (expand the y axis limits) with click or wheel'
         ' mouse (bidirectional)',
         gtk.STOCK_ZOOM_OUT, 'zoomy', -1, True),
        (None, None, None, None, None, None,),
        ('Save', 'Save the figure',
         gtk.STOCK_SAVE, 'save_figure', None, False),
        )
    
    def __init__(self, canvas, window=None):
        """
        figManager is the FigureManagerGTK instance that contains the
        toolbar, with attributes figure, window and drawingArea
        
        """
        gtk.Toolbar.__init__(self)

        self.canvas = canvas
        self.win    = window
        
        self.set_style(gtk.TOOLBAR_ICONS)

        if gtk.pygtk_version >= (2,3,97):
            self._create_toolitems_2_4()
            self.update = self._update_2_4
            self.fileselect = FileChooserDialog(title='Save the figure',
                                                parent=self.win)
        else:
            self._create_toolitems_2_2()
            self.update = self._update_2_2
            self.fileselect = FileSelection(path=None,
                                            title='Save the figure',
                                            parent=self.win)
        self.show_all()            
        self.update()


    def _create_toolitems_2_4(self):
        # use the GTK+ 2.4 GtkToolbar API
        iconSize = gtk.ICON_SIZE_SMALL_TOOLBAR
        self.tooltips = gtk.Tooltips()

        for text, tooltip_text, image, callback, callback_arg, scroll \
                in self.toolitems:
            if text is None:
                self.insert( gtk.SeparatorToolItem(), -1 )
                continue
            tbutton = gtk.ToolButton(gtk.image_new_from_stock(image, iconSize),
                                     text)
            self.insert(tbutton, -1)
            if callback_arg:
                tbutton.connect('clicked', getattr(self, callback), callback_arg)
            else:
                tbutton.connect('clicked', getattr(self, callback))
            if scroll:
                tbutton.connect('scroll_event', getattr(self, callback))
            tbutton.set_tooltip(self.tooltips, tooltip_text, 'Private')

        # Axes toolitem, is empty at start, update() adds a menu if >=2 axes
        self.axes_toolitem = gtk.ToolItem()
        self.insert(self.axes_toolitem, 0)
        self.axes_toolitem.set_tooltip(self.tooltips,
                                       tip_text='Select axes that controls affect',
                                       tip_private = 'Private')

        align = gtk.Alignment (xalign=0.5, yalign=0.5, xscale=0.0, yscale=0.0)
        self.axes_toolitem.add(align)

        self.menubutton = gtk.Button ("Axes")
        align.add (self.menubutton)

        def position_menu (menu):
            """Function for positioning a popup menu.
            Place menu below the menu button, but ensure it does not go off
            the bottom of the screen.
            The default is to popup menu at current mouse position
            """
            x0, y0    = self.window.get_origin()      
            x1, y1, m = self.window.get_pointer()     
            x2, y2    = self.menubutton.get_pointer() 
            sc_h      = self.get_screen().get_height()  # requires GTK+ 2.2 +
            w, h      = menu.size_request()

            x = x0 + x1 - x2
            y = y0 + y1 - y2 + self.menubutton.allocation.height
            y = min(y, sc_h - h)
            return x, y, True
        
        def button_clicked (button, data=None):
            self.axismenu.popup (None, None, position_menu, 0, gtk.get_current_event_time())

        self.menubutton.connect ("clicked", button_clicked)

        
    def _update_2_4(self):
        # for GTK+ 2.4+
        # called by __init__() and FigureManagerGTK
        
        self._axes = self.canvas.figure.axes

        if len(self._axes) >= 2:
            self.axismenu = self._make_axis_menu()
            self.menubutton.show_all()
        else:
            self.menubutton.hide()
            
        self.set_active(range(len(self._axes)))


    def _create_toolitems_2_2(self):
        # use the GTK+ 2.2 (and lower) GtkToolbar API
        iconSize = gtk.ICON_SIZE_SMALL_TOOLBAR

        for text, tooltip_text, image, callback, callback_arg, scroll \
                in self.toolitems:
            if text == None:
                self.append_space()
                continue
            item = self.append_item(text, tooltip_text, 'Private',
                                    gtk.image_new_from_stock(image, iconSize),
                                    getattr(self, callback), callback_arg)
            if scroll:
                item.connect("scroll_event", getattr(self, callback))

        self.omenu = gtk.OptionMenu()
        self.omenu.set_border_width(3)
        self.insert_widget(
            self.omenu,
            'Select axes that controls affect',
            'Private', 0)


    def _update_2_2(self):
        # for GTK+ 2.2 and lower
        # called by __init__() and FigureManagerGTK
        
        self._axes = self.canvas.figure.axes
        #self.set_active(range(len(self._axes))) # duplicates line below
        
        if len(self._axes) >= 2:                
            # set up the axis menu
            self.omenu.set_menu( self._make_axis_menu() )
            self.omenu.show_all()
        else:
            self.omenu.hide()
            
        self.set_active(range(len(self._axes))) 


    def _make_axis_menu(self):
        # called by self._update*()

        def toggled(item, data=None):
            if item == self.itemAll:
                for item in items: item.set_active(True)
            elif item == self.itemInvert:
                for item in items:
                    item.set_active(not item.get_active())

            ind = [i for i,item in enumerate(items) if item.get_active()]
            self.set_active(ind)
            
        menu = gtk.Menu()

        self.itemAll = gtk.MenuItem("All")
        menu.append(self.itemAll)
        self.itemAll.connect("activate", toggled)

        self.itemInvert = gtk.MenuItem("Invert")
        menu.append(self.itemInvert)
        self.itemInvert.connect("activate", toggled)

        items = []
        for i in range(len(self._axes)):
            item = gtk.CheckMenuItem("Axis %d" % (i+1))
            menu.append(item)
            item.connect("toggled", toggled)
            item.set_active(True)
            items.append(item)

        menu.show_all()
        return menu
    

    def set_active(self, ind):
        self._ind = ind
        self._active = [ self._axes[i] for i in self._ind ]
        
    def panx(self, button, arg):
        """arg is either user callback data or a scroll event
        """
        try:
            if arg.direction == gdk.SCROLL_UP: direction=1
            else: direction=-1
        except AttributeError:
            direction = arg

        for a in self._active:
            a.panx(direction)
        self.canvas.draw()
        return True
    
    def pany(self, button, arg):
        try:
            if arg.direction == gdk.SCROLL_UP: direction=1
            else: direction=-1
        except AttributeError:
            direction = arg

        for a in self._active:
            a.pany(direction)
        self.canvas.draw()
        return True
    
    def zoomx(self, button, arg):
        try:
            if arg.direction == gdk.SCROLL_UP: direction=1
            else: direction=-1
        except AttributeError:
            direction = arg

        for a in self._active:
            a.zoomx(direction)
        self.canvas.draw()
        return True

    def zoomy(self, button, arg):
        try:
            if arg.direction == gdk.SCROLL_UP: direction=1
            else: direction=-1
        except AttributeError:
            direction = arg

        for a in self._active:
            a.zoomy(direction)
        self.canvas.draw()
        return True


    def save_figure(self, button):
        fname = self.fileselect.get_filename_from_user()
        if fname:
            try: self.canvas.print_figure(fname)
            except IOError, msg:
                error_msg_gtk('Failed to save %s: Error msg was\n\n%s' % (
                    fname, '\n'.join(map(str, msg))),
                              self.win)
            

class FileSelection(gtk.FileSelection):
    """GTK+ 2.2 and lower file selector which remembers the last
    file/directory selected
    """
    def __init__(self, path=None, title='Select a file', parent=None):
        super(FileSelection, self).__init__(title)

        if path: self.path = path
        else:    self.path = os.getcwd() + os.sep

        if parent: self.set_transient_for(parent)
            
    def get_filename_from_user(self, path=None, title=None):
        if path:  self.path = path
        if title: self.set_title(title)
        self.set_filename(self.path)

        filename = None
        if self.run() == gtk.RESPONSE_OK:
            self.path = filename = self.get_filename()
        self.hide()
        return filename
    

if gtk.pygtk_version >= (2,3,97):
    class FileChooserDialog(gtk.FileChooserDialog):
        """GTK+ 2.4 file selector which remembers the last
        file/directory selected
        """
        def __init__ (self,
                      title   = 'Save file',
                      parent  = None,
                      action  = gtk.FILE_CHOOSER_ACTION_SAVE,
                      buttons = (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                 gtk.STOCK_SAVE,   gtk.RESPONSE_OK),
                      backend = '',
                      path    = None):
            super (FileChooserDialog, self).__init__ (title, parent, action,
                                                      buttons, backend)
            if path: self.path = path
            else:    self.path = os.getcwd() + os.sep

        def get_filename_from_user (self, path=None, title=None):
            if path:  self.path = path
            if title: self.set_title (title)
            if self.path.endswith ('/'):
                self.set_current_folder (self.path)
            else:
                self.set_filename (self.path)

            filename = None
            if self.run() == gtk.RESPONSE_OK:
                self.path = filename = self.get_filename()
            self.hide()
            return filename


FigureManager = FigureManagerGTK
error_msg = error_msg_gtk

# set icon used when windows are minimized
if gtk.pygtk_version >= (2,2,0):
    basedir = matplotlib.rcParams['datapath']
    fname = os.path.join(basedir, 'matplotlib.svg')
    try:   gtk.window_set_default_icon_from_file (fname)
    except:
        print >>sys.stderr, 'Could not load matplotlib icon:', sys.exc_info()[1]
