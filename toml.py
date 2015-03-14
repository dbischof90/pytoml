import string, re

class TomlError(RuntimeError):
    def __init__(self, kind, line, col):
        self.kind = kind
        self.line = line
        self.col = col
        RuntimeError.__init__(self, kind)

    def __str__(self):
        return '%s(%d, %d)' % (self.kind, self.line, self.col)

class _CharSource:
    def __init__(self, s):
        self._s = s
        self._index = 0
        self._mark = 0
        self._line = 1
        self._col = 1
        self._update_cur()

    def __bool__(self):
        return self.cur is not None

    def __len__(self):
        return len(self._s[self._index:])

    def __getitem__(self, item):
        return self._s[self._index:][item]

    def next(self, l=1):
        for ch in self[:l]:
            if ch == '\n':
                self._line += 1
                self._col = 1
            else:
                self._col += 1
        self._index += l
        self._update_cur()

    def mark(self):
        self._mark = self._index
        self._mark_pos = self._line, self._col

    def rollback(self):
        self._index = self._mark
        self._line, self._col = self._mark_pos
        self._update_cur()

    def commit(self, type=None, text=None):
        tok = self._s[self._mark:self._index]
        pos = (self._mark_pos, (self._line, self._col))
        if type is None:
            type = tok
        if text is None:
            text = tok
        return type, text, pos

    def error(self, kind):
        raise TomlError(kind, self._line, self._col)

    def _update_cur(self):
        self.tail = self._s[self._index:]
        if self._index < len(self._s):
            self.cur = self._s[self._index]
        else:
            self.cur = None

def lex(s):
    src = _CharSource(s.replace('\r\n', '\n'))
    def is_id(ch):
        return ch is not None and (ch.isalnum() or ch in '-_')

    def is_ws(ch):
        return ch is not None and ch in ' \t'

    def fetch_esc():
        escapes = {'b':'\b', 't':'\t', 'n':'\n', 'f':'\f', 'r':'\r', '"':'"', '\\':'\\'}
        if src.cur == 'u':
            if len(src) < 5 or any(ch not in string.hexdigits for ch in src[1:5]):
                src.error('invalid_escape_sequence')
            res = unichr(int(src[1:5], 16))
            src.next(5)
        elif src.cur == 'U':
            if len(src) < 9 or any(ch not in string.hexdigits for ch in src[1:9]):
                src.error('invalid_escape_sequence')
            res = unichr(int(src[1:9], 16))
            src.next(9)
        elif src.cur == '\n':
            while src and src.cur in ' \n\t':
                src.next()
            res = ''
        elif src.cur in escapes:
            res = escapes[src.cur]
            src.next(1)
        else:
            src.error('invalid_escape_sequence')
        return res

    datetime_re = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})')
    def consume_datetime():
        m = datetime_re.match(src.tail)
        if not m:
            return False
        src.next(len(m.group(0)))
        return True

    def consume_int():
        if not src:
            src.error('malformed')
        if src.cur in '+-':
            src.next()
        if not src or src.cur not in '0123456789':
            src.error('malformed')
        while src and src.cur in '0123456789_':
            src.next()

    def consume_float():
        consume_int()
        type = 'int'
        if src and src.cur == '.':
            type = 'float'
            src.next()
            if not src or src.cur not in '0123456789_':
                src.error('malformed_float')
            while src and src.cur in '0123456789_':
                src.next()
        if src and src.cur in 'eE':
            type = 'float'
            src.next()
            consume_int()
        return type

    while src:
        src.mark()
        if src.cur in ' \t':
            src.next()
            while src and src.cur in ' \t':
                src.next()
        elif src.cur == '#':
            src.next()
            while src and src.cur != '\n':
                src.next()
        elif src.cur in '0123456789':
            if consume_datetime():
                yield src.commit('datetime')
            else:
                src.rollback()
                type = consume_float()
                yield src.commit(type)
        elif src.cur in '+-':
            type = consume_float()
            yield src.commit(type)
        elif is_id(src.cur):
            while is_id(src.cur):
                src.next()
            yield src.commit('id')
        elif src.cur in '[]{}=.,\n':
            src.next()
            yield src.commit()
        elif src.tail.startswith("'''"):
            src.next(3)
            if src.cur == '\n':
                src.next()
            end_quote = src.tail.find("'''")
            if end_quote == -1:
                src.error('unclosed_multiline_string')
            text = src[:end_quote]
            src.next(end_quote+3)
            yield src.commit('str', text)
        elif src.cur == "'":
            src.next()
            end_quote = src.tail.find("'")
            if end_quote == -1:
                src.error('unclosed_string')
            text = src[:end_quote]
            src.next(end_quote+1)
            yield src.commit('str', text)
        elif src.tail.startswith('"""'):
            src.next(3)
            if src.cur == '\n':
                src.next()
            res = []
            while True:
                src.mark()
                end_quote = src.tail.find('"""')
                if end_quote == -1:
                    src.error('unclosed_multiline_string')
                esc_pos = src.tail.find('\\')
                if esc_pos == -1 or esc_pos > end_quote:
                    res.append(src[:end_quote])
                    src.next(end_quote+3)
                    break
                res.append(src[:esc_pos])
                src.next(esc_pos+1)
                res.append(fetch_esc())

            yield src.commit('str', ''.join(res))
        elif src.cur == '"':
            src.next()
            res = []
            while True:
                src.mark()
                end_quote = src.tail.find('"')
                if end_quote == -1:
                    src.error('unclosed_string')
                esc_pos = src.tail.find('\\')
                if esc_pos == -1 or esc_pos > end_quote:
                    res.append(src[:end_quote])
                    src.next(end_quote+1)
                    break
                res.append(src[:esc_pos])
                src.next(esc_pos+1)
                res.append(fetch_esc())

            yield src.commit('str', ''.join(res))
        else:
            src.error('unexpected_char')

    src.mark()
    yield src.commit('\n', '')
    yield src.commit('eof', '')

class _TokSource:
    def __init__(self, s):
        self._lex = iter(lex(s))
        self.pos = None
        self.next()

    def next(self):
        self.prev_pos = self.pos
        self.tok, self.text, self.pos = next(self._lex)

    def consume(self, kind):
        if self.tok == kind:
            self.next()
            return True
        return False

    def consume_adjacent(self, kind):
        if self.prev_pos is None or self.prev_pos[1] != self.pos[0]:
            return False
        return self.consume(kind)

    def consume_nls(self):
        while self.consume('\n'):
            pass

    def error(self, kind):
        raise TomlError(kind, self.pos[0][0], self.pos[0][1])

def _translate_literal(type, text):
    if type == 'bool':
        return text == 'true'
    elif type == 'int':
        return int(text.replace('_', ''))
    elif type == 'float':
        return float(text.replace('_', ''))
    elif type == 'str':
        return text
    elif type == 'datetime':
        return text

def load(fin, translate_literal=_translate_literal, translate_array=id):
    return loads(fin.read(), translate_literal=translate_literal, translate_array=translate_array)

def loads(s, translate_literal=_translate_literal, translate_array=id):
    if isinstance(s, str):
        s = s.decode('utf-8')

    toks = _TokSource(s)

    def read_value():
        while True:
            if toks.tok == 'id':
                if toks.text in ('true', 'false'):
                    value = translate_literal('bool', toks.text)
                    toks.next()
                    return 'bool', value
                else:
                    toks.error('unexpected_identifier')
            elif toks.tok in ('int', 'str', 'float', 'datetime'):
                type = toks.tok
                value = translate_literal(toks.tok, toks.text)
                toks.next()
                return type, value
            elif toks.consume('['):
                res = []
                toks.consume_nls()
                if not toks.consume(']'):
                    toks.consume_nls()
                    type, val = read_value()
                    res.append(val)
                    toks.consume_nls()
                    while toks.consume(','):
                        toks.consume_nls()
                        if toks.consume(']'):
                            break
                        cur_type, val = read_value()
                        if type != cur_type:
                            toks.error('heterogenous_array')
                        res.append(val)
                        toks.consume_nls()
                    else:
                        if not toks.consume(']'):
                            toks.error('expected_right_brace')
                return 'array', translate_array(res)
            elif toks.consume('{'):
                res = {}
                while toks.tok in ('id', 'str'):
                    k = toks.text
                    toks.next()
                    if k in res:
                        toks.error('duplicate_key')
                    if not toks.consume('='):
                        toks.error('expected_equals')
                    type, v = read_value()
                    res[k] = v
                    if not toks.consume(','):
                        break
                if not toks.consume('}'):
                    toks.error('expected_closing_brace')
                return 'table', res
            else:
                toks.error('unexpected_token')

    root = {}
    tables = {}
    scope = root

    while toks.tok != 'eof':
        if toks.tok in ('id', 'str'):
            k = toks.text
            toks.next()
            if not toks.consume('='):
                toks.error('expected_equals')
            type, v = read_value()
            if k in scope:
                toks.error('duplicate_keys')
            scope[k] = v
        elif toks.consume('\n'):
            pass
        elif toks.consume('['):
            is_table_array = toks.consume_adjacent('[')

            path = []
            if toks.tok not in ('id', 'str'):
                toks.error('expected_table_name')
            path.append(toks.text)
            toks.next()
            while toks.consume('.'):
                if toks.tok not in ('id', 'str'):
                    toks.error('expected_table_name')
                path.append(toks.text)
                toks.next()
            if not toks.consume(']') or (is_table_array and not toks.consume_adjacent(']')):
                toks.error('malformed_table_name')
            if not toks.consume('\n'):
                toks.error('garbage_after_table_name')

            cur = tables
            for name in path[:-1]:
                if isinstance(cur.get(name), list):
                    d, cur = cur[name][-1]
                else:
                    d, cur = cur.setdefault(name, (None, {}))

            scope = {}
            name = path[-1]
            if name not in cur:
                if is_table_array:
                    cur[name] = [(scope, {})]
                else:
                    cur[name] = (scope, {})
            elif isinstance(cur[name], list):
                if not is_table_array:
                    toks.error('table_type_mismatch')
                cur[name].append((scope, {}))
            else:
                if is_table_array:
                    toks.error('table_type_mismatch')
                old_scope, next_table = cur[name]
                if old_scope is not None:
                    toks.error('duplicate_tables')
                cur[name] = (scope, next_table)
        else:
            toks.error('unexpected')

    def merge_tables(scope, tables):
        if scope is None:
            scope = {}
        for k, v in tables.iteritems():
            if k in scope:
                toks.error('key_table_conflict')
            if isinstance(v, list):
                scope[k] = [merge_tables(sc, tbl) for sc, tbl in v]
            else:
                scope[k] = merge_tables(v[0], v[1])
        return scope

    return merge_tables(root, tables)

if __name__ == '__main__':
    import sys, json
    t = sys.stdin.read()
    print json.dumps(loads(t), indent=4)
