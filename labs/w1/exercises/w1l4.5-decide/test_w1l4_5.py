"""w1l4.5 decide: apply the rule pre-registered in experiments/prompt-v2.toml, nothing else."""

from tradingresearch.paired import decide


def test_the_recorded_result_ships():
    got = decide((0.45, 0.95), 0.0)
    assert got == "ship", (
        f"decide returned {got!r} for primary CI [+0.450, +0.950] and guard diff +0.000. The rule: ship if the "
        "interval's low end is above 0 and parsed did not drop."
    )


def test_an_interval_that_includes_zero_does_not_ship():
    got = decide((-0.05, 0.60), 0.0)
    assert got == "keep baseline", (
        f"decide returned {got!r} for CI [-0.050, +0.600]: a mean of +0.28 is not enough when the interval includes 0"
    )


def test_an_interval_touching_zero_does_not_ship():
    got = decide((0.0, 0.60), 0.0)
    assert got == "keep baseline", (
        f"decide returned {got!r} for CI [+0.000, +0.600]: a low end of exactly 0 still allows no improvement. The rule "
        "says above 0, so 0 itself keeps the baseline."
    )
    got = decide((0.01, 0.60), 0.0)
    assert got == "ship", f"decide returned {got!r} for CI [+0.010, +0.600]: a low end just above 0 ships"


def test_any_low_end_above_zero_ships():
    got = {low: decide((low, 0.60), 0.0) for low in (1e-9, 0.0004, 0.01)}
    assert got == {1e-9: "ship", 0.0004: "ship", 0.01: "ship"}, (
        f"decide((low, +0.600), guard +0.000) gave {got}. Every low end here is above 0, so every one ships: the rule "
        "written before the run says above 0, with no margin, and a margin chosen now would be a new rule."
    )


def test_the_guard_on_both_sides_of_zero():
    got = {guard: decide((0.45, 0.95), guard) for guard in (-0.05, -0.001, -0.0004, -1e-9, 0.0, 0.05)}
    assert got == {-0.05: "keep baseline", -0.001: "keep baseline", -0.0004: "keep baseline", -1e-9: "keep baseline",
                   0.0: "ship", 0.05: "ship"}, (
        f"decide((0.45, 0.95), guard) gave {got}. The guard must not drop: any drop, however small, keeps the baseline; "
        "no change or a rise ships."
    )
