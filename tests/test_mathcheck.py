import pytest
from learning.mathcheck import verify_answer, verify_limit, verify_problem


@pytest.mark.parametrize('a,b,status', [('(x+1)**2','x**2+2*x+1','verified'), ('x+1','x+2','incorrect'), ('sqrt(x**2)','x','incorrect'), ('解释连续性','0','undetermined'), ('__import__("os").system("whoami")','0','undetermined'), ('9**999999','0','undetermined'), ('x/x','1','undetermined')])
def test_answers(a, b, status):
    assert verify_answer(a,b,variables=['x'],timeout=5)['status'] == status


def test_positive_domain():
    assert verify_answer('sqrt(x**2)','x',variables=['x'],domain='positive',timeout=5)['status'] == 'verified'


def test_two_sided_limit_and_one_sided():
    assert verify_limit('1/x','x','0','oo')['status'] == 'incorrect'
    assert verify_limit('1/x','x','0','oo',direction='+')['status'] == 'verified'
    assert verify_limit('sin(x)/x','x','0','1')['status'] == 'verified'


def test_timeout_and_invalid_domain():
    assert verify_answer('x','x',timeout=0)['status'] == 'undetermined'
    assert verify_answer('x','x',domain='unknown')['status'] == 'undetermined'


@pytest.mark.parametrize('kind,expression,expected,extra', [('derivative','x**3','3*x**2',{}),('integral','x','2',{'lower':'0','upper':'2'}),('value','x**2','9',{'point':'3'}),('limit','sin(x)/x','1',{'point':'0'})])
def test_independent_problem_verification(kind,expression,expected,extra):
    q={'expected_answer':expected,'verification':{'type':kind,'expression':expression,'variable':'x',**extra}}
    assert verify_problem(q)['status']=='verified'
    q['expected_answer']='999'
    assert verify_problem(q)['status']=='incorrect'


def test_problem_cannot_self_verify_or_override_expected():
    assert verify_problem({'expected_answer':'1','verification':{'type':'equivalence','expression':'1'}})['status']=='undetermined'
    assert verify_problem({'expected_answer':'9','verification':{'type':'value','expression':'2+2','expected':'4'}})['status']=='undetermined'


@pytest.mark.parametrize('answer,expected', [('log(x)-log(x)','0'),('sqrt(x)*sqrt(x)','x'),('tan(x)*cos(x)','sin(x)'),('x/x','1')])
def test_cancellation_keeps_original_domains(answer,expected):
    assert verify_answer(answer,expected,variables=['x'],timeout=5)['status']=='undetermined'


def test_problem_domain_and_singular_integral_require_review():
    for spec in [
        {'type':'value','expression':'x/x','point':'0'},
        {'type':'integral','expression':'1/x','lower':'1','upper':'-1'},
        {'type':'equivalence','expression':'x/x','reference':'1'},
    ]:
        assert verify_problem({'expected_answer':'1','verification':spec})['status']=='undetermined'
    assert verify_problem({'expected_answer':'x/x','verification':{'type':'derivative','expression':'x'}})['status']=='undetermined'
