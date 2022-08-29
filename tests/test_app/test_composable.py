import os
import pathlib
import pickle

from pickle import dumps, loads
from tempfile import TemporaryDirectory
from unittest import main
from unittest.mock import Mock

import pytest

from scitrack import CachingLogger

from cogent3.app import io as io_app
from cogent3.app import sample as sample_app
from cogent3.app.composable import (
    NotCompleted,
    __app_registry,
    appify,
    define_app,
    get_object_provenance,
    is_composable,
    user_function,
)
from cogent3.app.sample import min_length, omit_degenerates
from cogent3.app.translate import select_translatable
from cogent3.app.tree import quick_tree
from cogent3.app.typing import (
    SERIALISABLE_TYPE,
    AlignedSeqsType,
    PairwiseDistanceType,
)


__author__ = "Gavin Huttley"
__copyright__ = "Copyright 2007-2022, The Cogent Project"
__credits__ = ["Gavin Huttley", "Nick Shahmaras"]
__license__ = "BSD-3"
__version__ = "2022.8.24a1"
__maintainer__ = "Gavin Huttley"
__email__ = "Gavin.Huttley@anu.edu.au"
__status__ = "Alpha"


def test_composable():
    """correctly form string"""

    @define_app
    class app_dummyclass_1:
        def __init__(self, a):
            self.a = a

        def main(self, val: int) -> int:
            return val

    @define_app
    class app_dummyclass_2:
        def __init__(self, b):
            self.b = b

        def main(self, val: int) -> int:
            return val

    aseqfunc1 = app_dummyclass_1(1)
    aseqfunc2 = app_dummyclass_2(2)
    comb = aseqfunc1 + aseqfunc2
    expect = "app_dummyclass_1(a=1) + " "app_dummyclass_2(b=2)"
    got = str(comb)
    assert got == expect
    __app_registry.pop(get_object_provenance(app_dummyclass_1), None)
    __app_registry.pop(get_object_provenance(app_dummyclass_2), None)


def test_composables_once():
    """composables can only be used in a single composition"""

    @define_app
    class app_dummyclass_1:
        def __init__(self, a):
            self.a = a

        def main(self, val: int) -> int:
            return val

    @define_app
    class app_dummyclass_2:
        def __init__(self, b):
            self.b = b

        def main(self, val: int) -> int:
            return val

    @define_app
    class app_dummyclass_3:
        def __init__(self, c):
            self.c = c

        def main(self, val: int) -> int:
            return val

    one = app_dummyclass_1(1)
    two = app_dummyclass_2(2)
    three = app_dummyclass_3(3)
    one + three
    with pytest.raises(ValueError):
        two + three  # three already has an input

    __app_registry.pop(get_object_provenance(app_dummyclass_1), None)
    __app_registry.pop(get_object_provenance(app_dummyclass_2), None)
    __app_registry.pop(get_object_provenance(app_dummyclass_3), None)


def test_composable_to_self():
    """this should raise a ValueError"""

    @define_app
    class app_dummyclass_1:
        def __init__(self, a):
            self.a = a

        def main(self, val: int) -> int:
            return val

    app1 = app_dummyclass_1(1)
    with pytest.raises(ValueError):
        _ = app1 + app1

    __app_registry.pop(get_object_provenance(app_dummyclass_1), None)


def test_disconnect():
    """disconnect breaks all connections and allows parts to be reused"""

    @define_app
    class app_dummyclass_1:
        def __init__(self, a):
            self.a = a

        def main(self, val: int) -> int:
            return val

    @define_app
    class app_dummyclass_2:
        def __init__(self, b):
            self.b = b

        def main(self, val: int) -> int:
            return val

    @define_app
    class app_dummyclass_3:
        def __init__(self, c):
            self.c = c

        def main(self, val: int) -> int:
            return val

    aseqfunc1 = app_dummyclass_1(1)
    aseqfunc2 = app_dummyclass_2(2)
    aseqfunc3 = app_dummyclass_3(3)
    comb = aseqfunc1 + aseqfunc2 + aseqfunc3
    comb.disconnect()
    assert aseqfunc1.input is None
    assert aseqfunc3.input is None
    # should be able to compose a new one now
    aseqfunc1 + aseqfunc3

    __app_registry.pop(get_object_provenance(app_dummyclass_1), None)
    __app_registry.pop(get_object_provenance(app_dummyclass_2), None)
    __app_registry.pop(get_object_provenance(app_dummyclass_3), None)


def test_apply_to():
    """correctly applies iteratively"""
    from cogent3.core.alignment import SequenceCollection

    dstore = io_app.get_data_store("data", suffix="fasta", limit=3)
    reader = io_app.load_unaligned(format="fasta", moltype="dna")
    got = reader.apply_to(dstore, show_progress=False)
    assert len(got) == len(dstore)
    # should also be able to apply the results to another composable func
    min_length = sample_app.min_length(10)
    got = min_length.apply_to(got, show_progress=False)
    assert len(got) == len(dstore)
    # should work on a chained function
    proc = reader + min_length
    got = proc.apply_to(dstore, show_progress=False)
    assert len(got) == len(dstore)
    # and works on a list of just strings
    got = proc.apply_to([str(m) for m in dstore], show_progress=False)
    assert len(got) == len(dstore)
    # or a single string
    got = proc.apply_to(str(dstore[0]), show_progress=False)
    assert len(got) == 1
    assert isinstance(got[0], SequenceCollection)
    # raises ValueError if empty list
    with pytest.raises(ValueError):
        proc.apply_to([])

    # raises ValueError if list with empty string
    with pytest.raises(ValueError):
        proc.apply_to(["", ""])


def test_apply_to_strings():
    """apply_to handles strings as paths"""
    dstore = io_app.get_data_store("data", suffix="fasta", limit=3)
    dstore = [str(m) for m in dstore]
    with TemporaryDirectory(dir=".") as dirname:
        reader = io_app.load_aligned(format="fasta", moltype="dna")
        min_length = sample_app.min_length(10)
        outpath = os.path.join(os.getcwd(), dirname, "delme.tinydb")
        writer = io_app.write_db(outpath)
        process = reader + min_length + writer
        # create paths as strings
        r = process.apply_to(dstore, show_progress=False)
        assert len(process.data_store.logs) == 1
        process.data_store.close()


def test_apply_to_non_unique_identifiers():
    """should fail if non-unique names"""
    dstore = [
        "brca1.bats.fasta",
        "brca1.apes.fasta",
    ]
    with TemporaryDirectory(dir=".") as dirname:
        reader = io_app.load_aligned(format="fasta", moltype="dna")
        min_length = sample_app.min_length(10)
        process = reader + min_length
        with pytest.raises(ValueError):
            process.apply_to(dstore)


def test_apply_to_logging():
    """correctly creates log file"""
    dstore = io_app.get_data_store("data", suffix="fasta", limit=3)
    with TemporaryDirectory(dir=".") as dirname:
        reader = io_app.load_aligned(format="fasta", moltype="dna")
        min_length = sample_app.min_length(10)
        outpath = os.path.join(os.getcwd(), dirname, "delme.tinydb")
        writer = io_app.write_db(outpath)
        process = reader + min_length + writer
        r = process.apply_to(dstore, show_progress=False)
        # always creates a log
        assert len(process.data_store.logs) == 1
        process.data_store.close()


def test_apply_to_logger():
    """correctly uses user provided logger"""
    dstore = io_app.get_data_store("data", suffix="fasta", limit=3)
    with TemporaryDirectory(dir=".") as dirname:
        LOGGER = CachingLogger()
        reader = io_app.load_aligned(format="fasta", moltype="dna")
        min_length = sample_app.min_length(10)
        outpath = os.path.join(os.getcwd(), dirname, "delme.tinydb")
        writer = io_app.write_db(outpath)
        process = reader + min_length + writer
        r = process.apply_to(dstore, show_progress=False, logger=LOGGER)
        assert len(process.data_store.logs) == 1
        process.data_store.close()


def test_apply_to_invalid_logger():
    """incorrect logger value raises TypeError"""
    dstore = io_app.get_data_store("data", suffix="fasta", limit=3)
    for logger_val in (True, "somepath.log"):
        with TemporaryDirectory(dir=".") as dirname:
            reader = io_app.load_aligned(format="fasta", moltype="dna")
            min_length = sample_app.min_length(10)
            outpath = os.path.join(os.getcwd(), dirname, "delme.tinydb")
            writer = io_app.write_db(outpath)
            process = reader + min_length + writer
            with pytest.raises(TypeError):
                process.apply_to(dstore, show_progress=False, logger=logger_val)
            process.data_store.close()


def test_apply_to_not_completed():
    """correctly creates notcompleted"""
    dstore = io_app.get_data_store("data", suffix="fasta", limit=3)
    with TemporaryDirectory(dir=".") as dirname:
        reader = io_app.load_aligned(format="fasta", moltype="dna")
        # trigger creation of notcompleted
        min_length = sample_app.min_length(3000)
        outpath = os.path.join(os.getcwd(), dirname, "delme.tinydb")
        writer = io_app.write_db(outpath)
        process = reader + min_length + writer
        r = process.apply_to(dstore, show_progress=False)
        assert len(process.data_store.incomplete) == 3
        process.data_store.close()


def test_apply_to_not_partially_done():
    """correctly applies process when result already partially done"""
    dstore = io_app.get_data_store("data", suffix="fasta")
    num_records = len(dstore)
    with TemporaryDirectory(dir=".") as dirname:
        dirname = pathlib.Path(dirname)
        reader = io_app.load_aligned(format="fasta", moltype="dna")
        outpath = dirname / "delme.tinydb"
        writer = io_app.write_db(outpath)
        _ = writer(reader(dstore[0]))
        writer.data_store.close()

        writer = io_app.write_db(outpath, if_exists="ignore")
        process = reader + writer
        _ = process.apply_to(dstore, show_progress=False)
        writer.data_store.close()
        dstore = io_app.get_data_store(outpath)
        assert len(dstore) == num_records
        dstore.close()


def test_err_result():
    """excercise creation of NotCompletedResult"""
    result = NotCompleted("SKIP", "this", "some obj")
    assert not result
    assert result.origin == "this"
    assert result.message == "some obj"
    assert result.source is None

    # check source correctly deduced from provided object
    fake_source = Mock()
    fake_source.source = "blah"
    del fake_source.info
    result = NotCompleted("SKIP", "this", "err", source=fake_source)
    assert result.source == "blah"

    fake_source = Mock()
    del fake_source.source
    fake_source.info.source = "blah"
    result = NotCompleted("SKIP", "this", "err", source=fake_source)
    assert result.source == "blah"

    try:
        _ = 0
        raise ValueError("error message")
    except ValueError as err:
        result = NotCompleted("SKIP", "this", err.args[0])

    assert result.message == "error message"


def test_str():
    """str representation correctly represents parameterisations"""
    func = select_translatable()
    got = str(func)
    assert (
        got
        == "select_translatable(moltype='dna', gc=1, allow_rc=False,\ntrim_terminal_stop=True)"
    )

    func = select_translatable(allow_rc=True)
    got = str(func)
    assert (
        got
        == "select_translatable(moltype='dna', gc=1, allow_rc=True, trim_terminal_stop=True)"
    )

    nodegen = omit_degenerates()
    got = str(nodegen)
    assert got == "omit_degenerates(moltype=None, gap_is_degen=True, motif_length=1)"
    ml = min_length(100)
    got = str(ml)
    assert (
        got
        == "min_length(length=100, motif_length=1, subtract_degen=True, moltype=None)"
    )

    qt = quick_tree()
    assert str(qt) == "quick_tree(drop_invalid=False)"


def test_composite_pickleable():
    """composable functions should be pickleable"""

    from cogent3.app import align, evo, io, sample, translate, tree

    read = io.load_aligned(moltype="dna")
    dumps(read)
    trans = translate.select_translatable()
    dumps(trans)
    aln = align.progressive_align("nucleotide")
    dumps(aln)
    just_nucs = sample.omit_degenerates(moltype="dna")
    dumps(just_nucs)
    limit = sample.fixed_length(1000, random=True)
    dumps(limit)
    mod = evo.model("HKY85")
    dumps(mod)
    qt = tree.quick_tree()
    dumps(qt)
    proc = read + trans + aln + just_nucs + limit + mod
    dumps(proc)


def test_not_completed_result():
    """should survive roundtripping pickle"""
    err = NotCompleted("FAIL", "mytest", "can we roundtrip")
    p = dumps(err)
    new = loads(p)
    assert err.type == new.type
    assert err.message == new.message
    assert err.source == new.source
    assert err.origin == new.origin


def test_triggers_bugcatcher():
    """a composable that does not trap failures returns NotCompletedResult
    requesting bug report"""
    from cogent3.app import io

    read = io.load_aligned(moltype="dna")
    read.main = lambda x: None
    got = read("somepath.fasta")
    assert isinstance(got, NotCompleted)
    assert got.type == "BUG"


def _demo(ctx, expect):
    return ctx.frame_start == expect


# for testing appify
@appify(SERIALISABLE_TYPE, SERIALISABLE_TYPE)
def slicer(val, index=2):
    """my docstring"""
    return val[:index]


@define_app
def foo(val: AlignedSeqsType, *args, **kwargs) -> AlignedSeqsType:
    return val[:4]


@define_app
def bar(val: AlignedSeqsType, num=3) -> PairwiseDistanceType:
    return val.distance_matrix(calc="hamming", show_progress=False)


def test_user_function():
    """composable functions should be user definable"""
    from cogent3 import make_aligned_seqs

    u_function = foo()

    aln = make_aligned_seqs(data=[("a", "GCAAGCGTTTAT"), ("b", "GCTTTTGTCAAT")])
    got = u_function(aln)

    assert got.to_dict() == {"a": "GCAA", "b": "GCTT"}

    __app_registry.pop(get_object_provenance(foo), None)


def test_user_function_multiple():
    """user defined composable functions should not interfere with each other"""
    from cogent3 import make_aligned_seqs
    from cogent3.core.alignment import Alignment

    u_function_1 = foo()
    u_function_2 = bar()

    aln_1 = make_aligned_seqs(data=[("a", "GCAAGCGTTTAT"), ("b", "GCTTTTGTCAAT")])
    data = dict([("s1", "ACGTACGTA"), ("s2", "GTGTACGTA")])
    aln_2 = Alignment(data=data, moltype="dna")

    got_1 = u_function_1(aln_1)
    got_2 = u_function_2(aln_2)
    assert got_1.to_dict() == {"a": "GCAA", "b": "GCTT"}
    assert got_2 == {("s1", "s2"): 2.0, ("s2", "s1"): 2.0}

    __app_registry.pop(get_object_provenance(foo), None)
    __app_registry.pop(get_object_provenance(bar), None)


def test_appify():
    """acts like a decorator should!"""
    assert slicer.__doc__ == "my docstring"
    assert slicer.__name__ == "slicer"
    app = slicer()
    assert SERIALISABLE_TYPE in app._input_types
    assert SERIALISABLE_TYPE in app._output_types
    assert app(list(range(4))) == [0, 1]
    app2 = slicer(index=3)
    assert app2(list(range(4))) == [0, 1, 2]


def test_appify_pickle():
    """appified function should be pickleable"""
    app = slicer(index=6)
    dumped = dumps(app)
    loaded = loads(dumped)
    assert loaded(list(range(10))) == list(range(6))


def test_user_function_repr():
    got = repr(bar(num=3))
    assert got == "bar(num=3)"


def test_user_function_str():
    got = str(bar(num=3))
    assert got == "bar(num=3)"


def test_user_function_with_args_kwargs():
    """correctly handles definition with args, kwargs"""
    from math import log

    def product(val, multiplier, take_log=False):
        result = val * multiplier
        if take_log:
            result = log(result)

        return result

    # without defining any args, kwargs
    ufunc = user_function(
        product,
        SERIALISABLE_TYPE,
        SERIALISABLE_TYPE,
    )
    assert ufunc(2, 2) == 4
    assert ufunc(2, 2, take_log=True) == log(4)

    # defining default arg2
    ufunc = user_function(
        product,
        SERIALISABLE_TYPE,
        SERIALISABLE_TYPE,
        2,
    )
    assert ufunc(2) == 4
    assert ufunc(2, take_log=True) == log(4)

    # defining default kwarg only
    ufunc = user_function(product, SERIALISABLE_TYPE, SERIALISABLE_TYPE, take_log=True)
    assert ufunc(2, 2) == log(4)
    assert ufunc(2, 2, take_log=False) == 4

    # defining default arg and kwarg
    ufunc = user_function(
        product, SERIALISABLE_TYPE, SERIALISABLE_TYPE, 2, take_log=True
    )
    assert ufunc(2) == log(4)


def test_app_registry():
    """correctly registers apps"""

    @define_app
    class app_test_registry1:
        def main(self, data: int) -> int:
            return data

    assert __app_registry["test_composable.app_test_registry1"]

    # delete it to not include in app available apps
    __app_registry.pop(get_object_provenance(app_test_registry1), None)


def test_app_is_composable():
    """check is_composable for composable apps"""

    @define_app
    class app_test_iscomposable1:
        def main(self, data: int) -> int:
            return data

    assert is_composable(app_test_iscomposable1)

    # delete it to not include in app available apps
    __app_registry.pop(get_object_provenance(app_test_iscomposable1), None)


def test_app_is_not_composable():
    """check is_composable for non-composable apps"""

    class app_not_composable1:
        def main(self, data: int) -> int:
            return data

    assert not is_composable(app_not_composable1)


def test_concat_not_composable():
    from cogent3.app.sample import concat

    assert not is_composable(concat)


def test_composed_func_pickleable():
    from cogent3.app.sample import min_length, omit_degenerates

    ml = min_length(100)
    no_degen = omit_degenerates(moltype="dna")
    app = ml + no_degen

    unpickled = pickle.loads(pickle.dumps((app)))
    assert unpickled.input is not None


def test_composable_new1():
    """correctly associate argument vals with their names when have variable
    positional args"""

    @define_app
    class pos_var_pos1:
        def __init__(self, a, b, *args):
            self.a = a
            self.b = b
            self.args = args

        def main(self, val: int) -> int:
            return val

    instance = pos_var_pos1(2, 3, 4, 5, 6)
    assert instance._init_vals == {"a": 2, "b": 3, "args": (4, 5, 6)}

    __app_registry.pop(get_object_provenance(pos_var_pos1), None)


def test_composable_new2():
    """correctly associate argument vals with their names when have variable
    positional args and kwargs"""

    @define_app
    class pos_var_pos_kw2:
        def __init__(self, a, *args, c=False):
            self.a = a
            self.c = c
            self.args = args

        def main(self, val: int) -> int:
            return val

    instance = pos_var_pos_kw2(2, 3, 4, 5, 6, c=True)
    assert instance._init_vals == {"a": 2, "args": (3, 4, 5, 6), "c": True}

    __app_registry.pop(get_object_provenance(pos_var_pos_kw2), None)


def test_app_decoration_fails_with_slots():
    with pytest.raises(NotImplementedError):

        @define_app
        class app_not_supported_slots1:
            __slots__ = ("a",)

            def __init__(self, a):
                self.a = a

            def main(self, val: int) -> int:
                return val


def test_repeated_decoration():
    @define_app
    class app_decorated_repeated1:
        def __init__(self, a):
            self.a = a

        def main(self, val: int) -> int:
            return val

    with pytest.raises(TypeError):
        define_app(app_decorated_repeated1)

    __app_registry.pop(get_object_provenance(app_decorated_repeated1), None)


def test_recursive_decoration():
    @define_app
    class app_docorated_recursive1:
        def __init__(self, a):
            self.a = a

        def main(self, val: int) -> int:
            define_app(app_docorated_recursive1)
            return val

    with pytest.raises(TypeError):
        app_docorated_recursive1().main(1)

    __app_registry.pop(get_object_provenance(app_docorated_recursive1), None)


def test_inheritance_from_decorated_class():
    @define_app
    class app_decorated_first1:
        def __init__(self, a):
            self.a = a

        def main(self, val: int) -> int:
            return val

    with pytest.raises(TypeError):

        @define_app
        class app_inherits_decorated1(app_decorated_first1):
            def __init__(self, a):
                self.a = a

            def main(self, val: int) -> int:
                return val

    __app_registry.pop(get_object_provenance(app_decorated_first1), None)


# have to define this at module level for pickling to work
@define_app
def func2app(arg1: int, exponent: int) -> float:
    return arg1 ** exponent


def test_decorate_app_function():
    """works on functions now"""
    import inspect

    sqd = func2app(exponent=2)
    assert sqd(3) == 9
    assert inspect.isclass(func2app)

    __app_registry.pop(get_object_provenance(func2app), None)


def test_roundtrip_decorated_function():
    """decorated function can be pickled/unpickled"""
    import pickle

    sqd = func2app(exponent=2)
    u = pickle.loads(pickle.dumps(sqd))
    assert u(4) == 16

    __app_registry.pop(get_object_provenance(func2app), None)


if __name__ == "__main__":
    main()
