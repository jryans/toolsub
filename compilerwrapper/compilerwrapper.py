# Compiler wrapper base class.
# Understands argstrings of cc/gcc/...-like compilers.
# Always compiles via .o, even if the user is asking to link as well.
# Also supports fixing up output .o files e.g. to support symbol interposition.

import os, sys, re, subprocess, tempfile, abc
import abc

class CompilerWrapper:
    __metaclass__ = abc.ABCMeta
    
    @abc.abstractmethod
    def getUnderlyingCompilerCommand(self):
        """return a list of strings that is the command (including arguments) to invoke
           the underlying compiler"""
        return
    
    @abc.abstractmethod
    def makeObjectFileName(self, sourceFileName):
        """return a sensible name for an object file given an input source file name"""
        return

    def getCustomCompileArgs(self, sourceInputFiles):
        return []
    
    def isLinkCommand(self):
        seenLib = False
        seenExecutableOutput = False
        for argnum in range(0,len(sys.argv)):
            arg = sys.argv[argnum]
            if arg.startswith('-l'):
                seenLib = True
            if arg == '-shared' or arg == '-G':
                return True
            if arg == '-c':
                return False
            if arg == "-o" and len(sys.argv) >= argnum + 2 and not '.' in os.path.basename(sys.argv[argnum + 1]):
                seenExecutableOutput = True
        if seenExecutableOutput:
            return True
        # NOTE: we don't use seenLib currently, since we often link simple progs without any -l
        return False
   
    def allWrappedSymNames(self):
        return []
    
    def parseInputAndOutputFiles(self, args):
        skipNext = False
        outputFile = None
        sourceInputFiles = []
        objectInputFiles = []
        for num in range(0,len(args)):
            if skipNext: 
                skipNext = False
                continue
            #if args[num] == "-V":
            #    args[num] = "-0"
            if args[num] == "-o":
                outputFile = args[num + 1]
                skipNext = True
            if args[num].startswith('-'):
                continue
            if num == 0:
                continue # this means we have "allocscc" as the arg
            if args[num].endswith('.o'):
                objectInputFiles += [args[num]]
            if args[num].endswith('.a') or args[num].endswith('.o') or \
                args[num].endswith('.so'):
                # it's a linker input; not the source file
                continue
            else:
                sys.stderr.write("guessed that source file is " + args[num] + "\n")
                sourceInputFiles += [args[num]]
        return (sourceInputFiles, objectInputFiles, outputFile)
   
    def fixupDotO(self, filename):
        # do we need to unbind? 
        # MONSTER HACK: globalize a symbol if it's a named alloc fn. 
        # This is needed e.g. for SPEC benchmark bzip2
        wrappedFns = self.allWrappedSymNames()
        sys.stderr.write("Looking for wrapped functions that need unbinding\n")
        cmdstring = "objdump -t \"%s\" | grep -v UND | egrep \"[ \\.](%s)$\"" \
            % (filename, "|".join(wrappedFns))
        sys.stderr.write("cmdstring is " + cmdstring + "\n")
        grep_ret = subprocess.call(["sh", "-c", cmdstring])
        if grep_ret == 0:
            # we need to unbind. We unbind the allocsite syms
            # *and* --prefer-non-section-relocs. 
            # This will give us a file with __def_ and __ref_ symbols
            # for the allocation function. We then rename these to 
            # __real_ and __wrap_ respectively. 
            backup_filename = os.path.splitext(filename)[0] + ".backup.o"
            sys.stderr.write("Found that we need to unbind... making backup as %s\n" % \
                backup_filename)
            subprocess.call(["cp", filename, backup_filename])
            unbind_pairs = [["--unbind-sym", sym] for sym in wrappedFns]
            objcopy_ret = subprocess.call(["objcopy", "--prefer-non-section-relocs"] \
             + [opt for pair in unbind_pairs for opt in pair] \
             + [filename])
            if objcopy_ret != 0:
                return objcopy_ret
            else:
                # one more objcopy to rename the __def_ and __ref_ symbols
                sys.stderr.write("Renaming __def_ and __ref_ alloc symbols\n")
                def_ref_args = [["--redefine-sym", "__def_" + sym + "=" + sym, \
                   "--redefine-sym", "__ref_" + sym + "=__wrap_" + sym] for sym in wrappedFns]
                objcopy_ret = subprocess.call(["objcopy", "--prefer-non-section-relocs"] \
                 + [opt for seq in def_ref_args for opt in seq] \
                 + [filename])
                if objcopy_ret != 0:
                    return objcopy_ret
        
        sys.stderr.write("Looking for wrapped functions that need globalizing\n")
        # grep for local symbols -- a lower-case letter after the symname is the giveaway
        cmdstring = "nm -fposix --defined-only \"%s\" | egrep \"^(%s) [a-z] \"" \
            % (filename, "|".join(wrappedFns))
        sys.stderr.write("cmdstring is %s\n" % cmdstring)
        grep_ret = subprocess.call(["sh", "-c", cmdstring])
        if grep_ret == 0:
            sys.stderr.write("Found that we need to globalize\n")
            globalize_pairs = [["--globalize-symbol", sym] for sym in wrappedFns]
            objcopy_ret = subprocess.call(["objcopy"] \
             + [opt for pair in globalize_pairs for opt in pair] \
             + [filename])
            return objcopy_ret
        # no need to objcopy; all good
        sys.stderr.write("No need to globalize\n")
        return 0

    def makeDotOAndPassThrough(self, argv, customArgs, inputFiles):
        argvWithoutOutputOptions = [argv[i] for i in range(0, len(argv)) \
           if argv[i] != '-o' and (i != 0 and argv[i-1] != '-o') and argv[i] != '-shared' and argv[i] != '-c' \
           and argv[i] != '-static']
        argvToPassThrough = [x for x in argv[1:] if not x in inputFiles]

        sys.stderr.write("Source input files: " + ', '.join(inputFiles) + "\n")
        sys.stderr.write("Custom args: " + ', '.join(customArgs) + "\n")
        sys.stderr.write("argv without output options: " + ', '.join(argvWithoutOutputOptions) + "\n")

        for sourceFile in inputFiles:
            # compile to .o with the custom args
            # -- erase -shared etc, and erase "-o blah"
            outputFilename = self.makeObjectFileName(sourceFile)
            sys.stderr.write("Building " + outputFilename + "\n")
            ret1 = subprocess.call(self.getUnderlyingCompilerCommand() + argvWithoutOutputOptions + customArgs \
            + ["-c", "-o", outputFilename, sourceFile])

            if ret1 != 0:
                # we didn't succeed, so quit now
                exit(ret1)
            else:
                ret2 = self.fixupDotO(outputFilename)
                if ret2 != 0:
                    # we didn't succeed, so quit now
                    exit(ret2)

                # include the .o file in our passed-through args
                argvToPassThrough += [outputFilename]

        sys.stderr.write("After making .o files, passing through arguments " + " ".join(argvToPassThrough) + "\n")
        return argvToPassThrough

