"""
Check that the output from irrational functions is accurate for
high-precision input, from 5 to 200 digits. The reference values were
verified with Mathematica.
"""

import time
from mpmath import *

precs = [5, 15, 28, 35, 57, 80, 100, 150, 200]

# sqrt(3) + pi/2
a = \
"3.302847134363773912758768033145623809041389953497933538543279275605"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# e + 1/euler**2
b = \
"5.719681166601007617111261398629939965860873957353320734275716220045750"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# sqrt(a)
sqrt_a = \
"1.817373691447021556327498239690365674922395036495564333152483422755"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# sqrt(a+b*i).real
sqrt_abi_real = \
"2.225720098415113027729407777066107959851146508557282707197601407276"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# sqrt(a+b*i).imag
sqrt_abi_imag = \
"1.2849057639084690902371581529110949983261182430040898147672052833653668"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# log(a)
log_a = \
"1.194784864491089550288313512105715261520511949410072046160598707069"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# log(a+b*i).real
log_abi_real = \
"1.8877985921697018111624077550443297276844736840853590212962006811663"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# log(a+b*i).imag
log_abi_imag = \
"1.0471204952840802663567714297078763189256357109769672185219334169734948"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# exp(a)
exp_a = \
"27.18994224087168661137253262213293847994194869430518354305430976149"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# exp(a+b*i).real
exp_abi_real = \
"22.98606617170543596386921087657586890620262522816912505151109385026"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# exp(a+b*i).imag
exp_abi_imag = \
"-14.523557450291489727214750571590272774669907424478129280902375851196283"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# a**b
pow_a_b = \
"928.7025342285568142947391505837660251004990092821305668257284426997"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# (a**(a+b*i)).real
pow_a_abi_real = \
"44.09156071394489511956058111704382592976814280267142206420038656267"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# (a**(a+b*i)).imag
pow_a_abi_imag = \
"27.069371511573224750478105146737852141664955461266218367212527612279886"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# ((a+b*i)**(a+b*i)).real
pow_abi_abi_real = \
"-0.15171310677859590091001057734676423076527145052787388589334350524"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"\

# ((a+b*i)**(a+b*i)).imag
pow_abi_abi_imag = \
"1.2697592504953448936553147870155987153192995316950583150964099070426"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# sin(a)
sin_a = \
"-0.16055653857469062740274792907968048154164433772938156243509084009"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# sin(1000*a)
sin_1000a = \
"-0.85897040577443833776358106803777589664322997794126153477060795801"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# sin(a+b*i)
sin_abi_real = \
"-24.4696999681556977743346798696005278716053366404081910969773939630"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

sin_abi_imag = \
"-150.42505378241784671801405965872972765595073690984080160750785565810981"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# cos
cos_a = \
"-0.98702664499035378399332439243967038895709261414476495730788864004"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

cos_1000a = \
"-0.51202523570982001856195696460663971099692261342827540426136215533"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

# tan
tan_a = \
"0.162666873675188117341401059858835168007137819495998960250142156848"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"

tan_abi_real = \
"6.822696615947538488826586186310162599974827139564433912601918442911"\
"REDACTED_MISTRAL"\
"467615882710035471686578162073677173148647065131872116479947620E-6"

tan_abi_imag = \
"0.9999795833048243692245661011298447587046967777739649018690797625964167"\
"REDACTED_MISTRAL"\
"REDACTED_MISTRAL"


def test_hp():
    for dps in precs:
        mp.dps = dps + 8
        aa = mpf(a)
        bb = mpf(b)
        a1000 = 1000*mpf(a)
        abi = mpc(aa, bb)
        mp.dps = dps
        assert (sqrt(3) + pi/2).ae(aa)
        assert (e + 1/euler**2).ae(bb)

        assert sqrt(aa).ae(mpf(sqrt_a))
        assert sqrt(abi).ae(mpc(sqrt_abi_real, sqrt_abi_imag))

        assert log(aa).ae(mpf(log_a))
        assert log(abi).ae(mpc(log_abi_real, log_abi_imag))

        assert exp(aa).ae(mpf(exp_a))
        assert exp(abi).ae(mpc(exp_abi_real, exp_abi_imag))

        assert (aa**bb).ae(mpf(pow_a_b))
        assert (aa**abi).ae(mpc(pow_a_abi_real, pow_a_abi_imag))
        assert (abi**abi).ae(mpc(pow_abi_abi_real, pow_abi_abi_imag))

        assert sin(a).ae(mpf(sin_a))
        assert sin(a1000).ae(mpf(sin_1000a))
        assert sin(abi).ae(mpc(sin_abi_real, sin_abi_imag))

        assert cos(a).ae(mpf(cos_a))
        assert cos(a1000).ae(mpf(cos_1000a))

        assert tan(a).ae(mpf(tan_a))
        assert tan(abi).ae(mpc(tan_abi_real, tan_abi_imag))

        # check that complex cancellation is avoided so that both
        # real and imaginary parts have high relative accuracy.
        # abs_eps should be 0, but has to be set to 1e-205 to pass the
        # 200-digit case, probably due to slight inaccuracy in the
        # precomputed input
        assert (tan(abi).real).ae(mpf(tan_abi_real), abs_eps=1e-205)
        assert (tan(abi).imag).ae(mpf(tan_abi_imag), abs_eps=1e-205)
    mp.dps = 460
    assert str(log(3))[-20:] == '02166121184001409826'
    mp.dps = 15

# Since str(a) can differ in the last digit from rounded a, and I want
# to compare the last digits of big numbers with the results in Mathematica,
# I made this hack to get the last 20 digits of rounded a

def last_digits(a):
    r = repr(a)
    s = str(a)
    #dps = mp.dps
    #mp.dps += 3
    m = 10
    r = r.replace(s[:-m],'')
    r = r.replace("mpf('",'').replace("')",'')
    num0 = 0
    for c in r:
        if c == '0':
            num0 += 1
        else:
            break
    b = float(int(r))/10**(len(r) - m)
    if b >= 10**m - 0.5:  # pragma: no cover
        raise NotImplementedError
    n = int(round(b))
    sn = str(n)
    s = s[:-m] + '0'*num0 + sn
    return s[-20:]

# values checked with Mathematica
def test_log_hp():
    mp.dps = 2000
    a = mpf(10)**15000/3
    r = log(a)
    res = last_digits(r)
    # Mathematica N[Log[10^15000/3], 2000]
    # ...7443804441768333470331
    assert res == '43804441768333470331'

    # see issue 145
    r = log(mpf(3)/2)
    # Mathematica N[Log[3/2], 2000]
    # ...69653749808140753263288
    res = last_digits(r)
    assert res == '53749808140753263288'

    mp.dps = 10000
    r = log(2)
    res = last_digits(r)
    # Mathematica  N[Log[2], 10000]
    # ...695615913401856601359655561
    assert res == '13401856601359655561'
    r = log(mpf(10)**10/3)
    res = last_digits(r)
    # Mathematica N[Log[10^10/3], 10000]
    # ...587087654020631943060007154
    assert res == '54020631943060007154', res
    r = log(mpf(10)**100/3)
    res = last_digits(r)
    # Mathematica N[Log[10^100/3], 10000]
    # ,,,59246336539088351652334666
    assert res == '36539088351652334666', res
    mp.dps += 10
    a = 1 - mpf(1)/10**10
    mp.dps -= 10
    r = log(a)
    res = last_digits(r)
    # ...3310334360482956137216724048322957404
    # 372167240483229574038733026370
    # Mathematica N[Log[1 - 10^-10]*10^10, 10000]
    # ...60482956137216724048322957404
    assert res == '37216724048322957404', res
    mp.dps = 10000
    mp.dps += 100
    a = 1 + mpf(1)/10**100
    mp.dps -= 100

    r = log(a)
    res = last_digits(+r)
    # Mathematica N[Log[1 + 10^-100]*10^10, 10030]
    # ...3994733877377412241546890854692521568292338268273 10^-91
    assert res == '39947338773774122415', res

    mp.dps = 15

def test_exp_hp():
    mp.dps = 4000
    r = exp(mpf(1)/10)
    # IntegerPart[N[Exp[1/10] * 10^4000, 4000]]
    # ...92167105162069688129
    assert int(r * 10**mp.dps) % 10**20 == 92167105162069688129
