from __future__ import division
import collections

import binUnpacker
import bytecode
from attributes_raw import get_attributes_raw

exceptionHandlerRaw = collections.namedtuple("exceptionHandlerRaw",
                                             ["start","end","handler","type_ind"])

class Code(object):
    def __init__(self, method, bytestream):
        self.method = method
        self.class_ = method.class_
        
        #Old versions use shorter fields for stack, locals, and code length
        field_fmt = ">HHL" if self.class_.version > (45,2) else ">BBH"
        self.stack, self.locals, codelen = bytestream.get(field_fmt)
        assert(codelen > 0 and codelen < 65536)
        self.bytecode_raw = bytestream.getRaw(codelen)
        self.codelen = codelen

        except_cnt = bytestream.get('>H')
        self.except_raw = [bytestream.get('>HHHH') for i in range(except_cnt)]
        self.except_raw = [exceptionHandlerRaw(*t) for t in self.except_raw]
        self.attributes_raw = get_attributes_raw(bytestream)
        assert(bytestream.size() == 0)

        if self.except_raw:
            assert(self.stack >= 1)

        # print 'Parsing code for', method.name, method.descriptor, method.flags
        codestream = binUnpacker.binUnpacker(data = self.bytecode_raw)
        self.bytecode = bytecode.parseInstructions(codestream, self.isIdConstructor)

        for e in self.except_raw:
            assert(e.start in self.bytecode)
            assert(e.end == codelen or e.end in self.bytecode)
            assert(e.handler in self.bytecode)

    #This is a callback passed to the bytecode parser to determine if a given method id represents a constructor                        
    def isIdConstructor(self, methId):
        args = self.class_.cpool.getArgsCheck('Method', methId) 
        return args[1] == '<init>'


    def __str__(self):
        lines = ['Stack: {}, Locals {}'.format(self.stack, self.locals)]
        
        instructions = self.bytecode
        lines += ['{}: {}'.format(i, bytecode.printInstruction(instructions[i])) for i in sorted(instructions)]
        if self.except_raw:
            lines += ['Exception Handlers:']
            lines += map(str, self.except_raw)
        return '\n'.join(lines)

class Method(object):
    flagVals = {'PUBLIC':0x0001,
                'PRIVATE':0x0002,
                'PROTECTED':0x0004,
                'STATIC':0x0008,
                'FINAL':0x0010,
                'SYNCHRONIZED':0x0020,
                'BRIDGE':0x0040,
                'VARARGS':0x0080,
                'NATIVE':0x0100,
                'ABSTRACT':0x0400,
                'STRICTFP':0x0800,
                'SYNTHETIC':0x1000, 
                }

    def __init__(self, data, classFile):
        self.class_ = classFile
        cpool = self.class_.cpool
        
        flags, self.name_id, self.desc_id, self.attributes = data

        self.name = cpool.getArgsCheck('Utf8', self.name_id)
        self.descriptor = cpool.getArgsCheck('Utf8', self.desc_id)
        # print 'Loading method ', self.name, self.descriptor

        self.flags = set(name for name,mask in Method.flagVals.items() if (mask & flags))
        self._checkFlags()
        self.static = 'STATIC' in self.flags
        self.native = 'NATIVE' in self.flags
        self.abstract = 'ABSTRACT' in self.flags

        self.isConstructor = (self.name == '<init>')
        
        #Prior to version 51.0, <clinit> is still valid even if it isn't marked static
        if self.class_.version < (51,0) and self.name == '<clinit>' and self.descriptor == '()V':
            self.static = True
        self._loadCode()

    def _checkFlags(self):
        assert(len(self.flags & set(('PRIVATE','PROTECTED','PUBLIC'))) <= 1)
        if 'ABSTRACT' in self.flags: 
            assert(not self.flags & set(['SYNCHRONIZED', 'PRIVATE', 'FINAL', 'STRICT', 'STATIC', 'NATIVE']))

    def _loadCode(self):
        cpool = self.class_.cpool
        code_attrs = [a for a in self.attributes if
                      cpool.getArgsCheck('Utf8', a[0]) == 'Code']
        if self.native or self.abstract:
            assert(not code_attrs)
            self.code = None
        else:
            assert(len(code_attrs) == 1)
            code_raw = code_attrs[0][1]
            bytestream = binUnpacker.binUnpacker(code_raw)
            self.code = Code(self, bytestream)