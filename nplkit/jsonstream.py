# CardOS streaming JSON reader, for API replies too big to hold in RAM.
# Feed it bytes as they arrive; it calls you back for each value, with its
# path, so you keep only the few fields you need.
#
#   def on_value(path, value): ...   # path: tuple of keys, "#" for list items
#   def on_open(path): ...           # an object/list starts at `path`
#   p = jsonstream.Parser(on_value, on_open)
#   p.feed(chunk)                    # call for every chunk received
#
# Strings and numbers arrive as str; true/false/null as "true"/"false"/"null".
# Escapes are simplified (\" -> ", \n -> n), which is fine for display text.
import micropython


class Parser:
    def __init__(self, on_value, on_open=None):
        self.on_value = on_value
        self.on_open = on_open
        self.stack = []          # [is_object, current_key] per open container
        self.want_key = False
        self.in_str = False
        self.esc = False
        self.s = bytearray()
        self.tok = bytearray()

    def path(self):
        return tuple(k if obj else "#" for obj, k in self.stack)

    def _string(self):
        text = self.s.decode()
        top = self.stack[-1] if self.stack else None
        if top is not None and top[0] and self.want_key:
            top[1] = text
        else:
            self.on_value(self.path(), text)

    def _literal(self):
        if self.tok:
            self.on_value(self.path(), self.tok.decode())
            self.tok = bytearray()

    @micropython.native
    def feed(self, data):
        for b in data:
            if self.in_str:
                if self.esc:
                    self.esc = False
                    self.s.append(b)
                elif b == 92:                  # backslash
                    self.esc = True
                elif b == 34:                  # closing quote
                    self.in_str = False
                    self._string()
                else:
                    self.s.append(b)
            elif b == 34:                      # opening quote
                self.in_str = True
                self.s = bytearray()
            elif b == 123 or b == 91:          # { [
                if self.on_open is not None:
                    self.on_open(self.path())
                self.stack.append([b == 123, None])
                self.want_key = b == 123
            elif b == 125 or b == 93:          # } ]
                self._literal()
                self.stack.pop()
            elif b == 44:                      # ,
                self._literal()
                if self.stack and self.stack[-1][0]:
                    self.want_key = True
            elif b == 58:                      # :
                self.want_key = False
            elif b > 32:
                self.tok.append(b)
