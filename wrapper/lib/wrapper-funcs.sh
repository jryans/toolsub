debug_print () {
    lvl="$1"
    shift
    if [[ "$DEBUG_CC" -ge $lvl ]]; then
        echo "$@"
    fi
}

is_pp () {
    saw_pp=0
    outpos=0
    while shift; do
        ctr="$(( $ctr + 1 ))"
        if [[ -z "$1" ]]; then continue; fi
        case "$1" in
         (-o) outfile="$2"; outpos="$(( $ctr + 1 ))";;
         (-E) saw_pp=1 ;;
        esac
    done
    # if we're only preprocessing, or if we have no explicit output file, just run cc1
    if [ "$saw_pp" -eq 0 ] || [ $outpos -eq 0 ]; then false; else true; fi
}

run_with_replacement_outfile () {
    replacement="$1"
    declare -a args
    ctr=0
    while shift; do
        ctr="$(( $ctr + 1 ))"
        if [[ -z "$1" ]]; then continue; fi
        case "$1" in
         (-o) args[$ctr]="$1"; args[$(( $ctr + 1 ))]="$replacement"; shift; ctr="$(( $ctr + 1 ))" ;;
         (*)  args[$ctr]="$1" ;;
        esac
    done
    debug_print 1 "Running + replacement outfile: ${args[@]}" 1>&2
    "${args[@]}"
}

run_with_replacement_infile () {
    # We are running cpp
    # PROBLEM: how do we identify the input filename?
    # Doing this generally means understanding cpp's entire command-line syntax.
    # We instead use a HACK:
    # for gcc we only need understand the options -E -quiet -imultiarch x86_64-linux-gnu
    # ... which (1) come first, and (2) cpp *doesn't* understand.
    replacement="$1"
    debug_print 1 "Trying to replace input file given args: $@" 1>&2
    shift
    declare -a args
    args[1]="$1"
    ctr=2
    orig_infile=""
    must_read_arg=""
    handle_possible_infile () {
        if [[ -z "$orig_infile" ]]; then
            debug_print 1 "We think the input file is $1" 1>&2
            orig_infile="$1";
            args[$ctr]="$replacement"
        else
            args[$ctr]="$1"
        fi
    }
    while shift; do
        ctr="$(( $ctr + 1 ))"
        if [[ -n "$must_read_arg" ]]; then
            args[$ctr]="$1"
            must_read_arg=""
            continue
        fi
        if [[ -z "$1" ]]; then continue; fi
        case "$1" in
            (-E|-quiet) ;; # skip it!
            (-D|-U|-include) must_read_arg=1; args[$ctr]="$1" ;;
            (-imultiarch) shift || break ;; # skip it and its arg!
            (--) no_more_options=1 ;;
            (-*) if [[ -z "$no_more_options" ]]; then args[$ctr]="$1"; else handle_possible_infile "$1"; fi ;;
            (*) handle_possible_infile "$1" ;;
        esac
    done
    debug_print 1 "Running + replacement infile ($replacement): ${args[@]}" 1>&2
    "${args[@]}"
}

guess_driver () {
    readlink /proc/$PPID/exe
}

# build the array of options to pass our preprocessing tool,
# using our own array of options
scrape_cpp_options () {
    driver="$(guess_driver)"
    debug_print 1 "driver binary is probably $driver" 1>&2
    debug_print 1 "outpos is $outpos" 1>&2
    debug_print 1 "outfile is $outfile" 1>&2
    # do the cpp, then run CIL
    debug_print 1 "We think we do have to substitute preprocessing; args $@" 1>&2
    cpp_options[0]="-driver"
    cpp_options[1]="$driver"
    ctr=2
    while shift || break; do
        debug_print 1 "\$# is $#, \$1 is '$1'" 1>&2
        case "$1" in
            # filter out non-cpp args
            ("-imultiarch") shift || break ;; # skip arg too
            ("-quiet") ;; # skip just it
            ('') ;; # FIXME: this shouldn't happen!
            (*)
                debug_print 1 "Snarfing $1" 1>&2
                cpp_options[$ctr]="$1"
                ctr=$(( $ctr + 1)) 
            ;;
        esac
    done
}