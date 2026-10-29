"""Conservative expression checking. User input is never executed."""
import ast
import math
import multiprocessing as mp
import re


def _normalize(text):
    """Accept common keyboard symbols without turning prose into executable code."""
    if not isinstance(text, str): return text
    return (text.replace('π','pi').replace('∞','oo').replace('×','*').replace('÷','/')
        .replace('−','-').replace('–','-').replace('≤','<=').replace('≥','>='))

def _parse(text, symbols):
    import sympy as s
    if not isinstance(text, str) or len(text) > 600:
        raise ValueError('Expression too long')
    tree = ast.parse(_normalize(text).strip().replace('^', '**'), mode='eval')
    if len(list(ast.walk(tree))) > 100:
        raise ValueError('Expression too complex')
    funcs = {'sin':s.sin,'cos':s.cos,'tan':s.tan,'exp':s.exp,'log':s.log,'sqrt':s.sqrt,'Abs':s.Abs,'abs':s.Abs}
    denominators = []
    def build(n, depth=0):
        if depth > 18: raise ValueError('Expression too deep')
        if isinstance(n, ast.Constant) and type(n.value) in (int,float):
            if not math.isfinite(n.value) or abs(n.value) > 100000: raise ValueError('Number too large')
            return s.Rational(str(n.value))
        if isinstance(n, ast.Name):
            if n.id in symbols: return symbols[n.id]
            if n.id in {'pi','E','oo'}: return {'pi':s.pi,'E':s.E,'oo':s.oo}[n.id]
            raise ValueError('Unknown symbol')
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.USub,ast.UAdd)):
            a = build(n.operand,depth+1); return -a if isinstance(n.op,ast.USub) else a
        if isinstance(n,ast.BinOp):
            a,b = build(n.left,depth+1),build(n.right,depth+1)
            if isinstance(n.op,ast.Add): return a+b
            if isinstance(n.op,ast.Sub): return a-b
            if isinstance(n.op,ast.Mult): return a*b
            if isinstance(n.op,ast.Div):
                if b == 0: raise ValueError('Division by zero')
                denominators.append(b); return a/b
            if isinstance(n.op,ast.Pow):
                if not b.is_number or b.is_real is not True or abs(b)>32: raise ValueError('Unsafe exponent')
                if b < 0: denominators.append(a)
                return a**b
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in funcs and len(n.args)==1 and not n.keywords:
            return funcs[n.func.id](build(n.args[0],depth+1))
        raise ValueError('Unsupported expression syntax')
    return build(tree.body), denominators


def _defined_domain(text, symbols, domain):
    """Inspect subexpressions before simplification can erase their restrictions."""
    import sympy as s
    base = s.Interval.open(0,s.oo) if domain=='positive' else s.S.Reals if domain=='real' else s.S.Complexes
    result = {name:base for name in symbols}
    tree = ast.parse(_normalize(text).strip().replace('^','**'), mode='eval')
    for node in ast.walk(tree):
        restricted = isinstance(node,ast.Call) or isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Div,ast.Pow))
        if not restricted: continue
        value, denominators = _parse(ast.unparse(node),symbols)
        variables = value.free_symbols | set().union(*(d.free_symbols for d in denominators))
        if len(variables)>1: raise ValueError('Multivariable domain requires review')
        if not variables: continue
        variable = next(iter(variables)); allowed=base
        if domain=='complex':
            if isinstance(node,ast.Call): raise ValueError('Complex function domain requires review')
        else:
            allowed = s.calculus.util.continuous_domain(value,variable,base)
        for denominator in denominators:
            zeros=s.solveset(denominator,variable,domain=base)
            if isinstance(zeros,s.ConditionSet): raise ValueError('Undetermined domain')
            allowed=allowed-zeros
        # Calls and powers are themselves parsed before their parent is simplified.
        result[str(variable)] = result[str(variable)].intersect(allowed)
    return result


def _work(conn, mode, args):
    import sympy as s
    try:
        if mode == 'answer':
            answer,expected,variables,domain = args
            if domain not in {'real','positive','complex'}: raise ValueError('Unsupported domain')
            if variables is None:
                names = set(re.findall(r'\b[a-zA-Z][a-zA-Z0-9_]*\b',answer+' '+expected)) - {'sin','cos','tan','exp','log','sqrt','Abs','abs','pi','E','oo'}
            else: names = set(variables)
            if len(names)>6 or any(not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,15}',n) for n in names): raise ValueError('Invalid variables')
            symbols = {n:s.Symbol(n, **({'positive':True} if domain=='positive' else {'real':True} if domain=='real' else {})) for n in names}
            a,ad = _parse(answer,symbols); b,bd = _parse(expected,symbols)
            if any(v.has(s.zoo,s.nan) for v in (a,b)): raise ValueError('Undefined expression')
            diff = s.simplify(a-b)
            if diff == 0:
                # Cancellation must not erase excluded points. Conservatively compare denominator zero sets.
                def excluded(ds):
                    out = s.EmptySet
                    for d in ds:
                        if len(d.free_symbols)>1: raise ValueError('Multivariable domain requires review')
                        if d.free_symbols:
                            var = next(iter(d.free_symbols))
                            roots = s.solveset(d,var,domain=s.Interval.open(0,s.oo) if domain=='positive' else s.S.Reals if domain=='real' else s.S.Complexes)
                            if isinstance(roots,s.ConditionSet): raise ValueError('Undetermined domain')
                            out = s.Union(out,roots)
                    return out
                if excluded(ad) != excluded(bd) or _defined_domain(answer,symbols,domain)!=_defined_domain(expected,symbols,domain): raise ValueError('Different excluded points require domain review')
                result = {'status':'verified','detail':'Symbolic equivalence on the declared domain; input exclusions preserved.'}
            else:
                unequal = diff.is_zero is False
                for val in ([1,2,3] if domain=='positive' else [-2,-1,0,1,2]):
                    evaluated = diff.subs({v:val for v in symbols.values()})
                    if not evaluated.has(s.zoo,s.nan,s.oo,-s.oo) and evaluated.is_zero is False: unequal=True; break
                result = {'status':'incorrect' if unequal else 'undetermined','detail':'Expressions differ.' if unequal else 'Equivalence could not be established.'}
        elif mode == 'problem':
            question=args[0]; spec=question.get('verification',{}); kind=spec.get('type')
            expected=question.get('expected_answer','')
            if not expected or ('expected' in spec and str(spec['expected'])!=str(expected)): raise ValueError('Conflicting answer key')
            variable=spec.get('variable','x')
            if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,15}',variable): raise ValueError('Invalid variable')
            domain=question.get('domain','real')
            if domain not in {'real','positive','complex'}: raise ValueError('Unsupported domain')
            x=s.Symbol(variable,**({'positive':True} if domain=='positive' else {'real':True} if domain=='real' else {}))
            expr,_=_parse(spec.get('expression',''),{variable:x})
            want,_=_parse(str(expected),{variable:x})
            if kind=='derivative': actual=s.diff(expr,x)
            elif kind=='integral':
                if 'lower' not in spec or 'upper' not in spec: raise ValueError('Definite bounds required')
                lower,_=_parse(str(spec['lower']),{variable:x}); upper,_=_parse(str(spec['upper']),{variable:x})
                # Internal poles require manual review, even when symbolic integration returns a principal value.
                poles=s.singularities(expr,x)
                interval=s.Interval(min(lower,upper),max(lower,upper)) if lower.is_number and upper.is_number else s.Interval(lower,upper)
                if poles.intersect(interval) != s.EmptySet: raise ValueError('Singular integral requires review')
                actual=s.integrate(expr,(x,lower,upper))
                if 'initial_value' in spec:
                    initial,_=_parse(str(spec['initial_value']),{}); actual+=initial
            elif kind=='value':
                p,_=_parse(str(spec.get('point','0')),{variable:x})
                allowed=_defined_domain(spec.get('expression',''),{variable:x},domain)[variable]
                if not p.free_symbols and allowed.contains(p) is not s.true: raise ValueError('Point outside expression domain')
                if p==x and allowed!=_defined_domain(str(expected),{variable:x},domain)[variable]: raise ValueError('Value expression domains disagree')
                actual=expr.subs(x,p)
            elif kind=='limit':
                p,_=_parse(str(spec.get('point','0')),{}); direction=spec.get('direction','both')
                if direction not in {'both','+','-'}: raise ValueError('Invalid direction')
                vals=[s.limit(expr,x,p,dir=d) for d in (['-','+'] if direction=='both' and p not in (s.oo,-s.oo) else [direction if direction!='both' else '+'])]
                if len(vals)==2 and vals[0]!=vals[1]:
                    conn.send({'status':'incorrect','detail':'Left and right limits disagree.'}); return
                actual=vals[0]
            elif kind=='equivalence':
                # Two independently specified formulations only; identity-to-itself is no evidence.
                if 'reference' not in spec or spec['reference']==spec['expression']: raise ValueError('Independent reference required')
                reference,_=_parse(str(spec['reference']),{variable:x})
                if s.simplify(expr-reference)!=0: raise ValueError('Reference formulations disagree')
                if _defined_domain(spec['expression'],{variable:x},domain)!=_defined_domain(spec['reference'],{variable:x},domain): raise ValueError('Reference domains disagree')
                actual=reference
            else: raise ValueError('Unsupported verification type')
            if actual.has(s.Integral,s.Derivative,s.Limit,s.zoo,s.nan): raise ValueError('Undetermined computation')
            diff=s.simplify(actual-want) if actual!=want else s.Integer(0)
            status='verified' if diff==0 else 'incorrect' if diff.is_zero is False else 'undetermined'
            if status=='verified' and _defined_domain(str(expected),{variable:x},domain)!=_defined_domain(str(actual),{variable:x},domain):
                raise ValueError('Answer key has different domain restrictions')
            if status=='undetermined':
                for value in ([1,2,3] if domain=='positive' else [-2,-1,0,1,2]):
                    probe=diff.subs(x,value)
                    if not probe.has(s.zoo,s.nan,s.oo,-s.oo) and probe.is_zero is False:
                        status='incorrect'; break
            result={'status':status,'detail':'Independent '+str(kind)+' computation compared with answer key.'}
        else:
            expression,variable,point,expected,direction = args
            if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,15}',variable) or direction not in {'both','+','-'}: raise ValueError('Invalid limit parameters')
            x=s.Symbol(variable,real=True)
            expr,_ = _parse(expression,{variable:x}); p,_ = _parse(str(point),{}); want,_ = _parse(str(expected),{})
            limits=[s.limit(expr,x,p,dir=d) for d in (['-','+'] if direction=='both' and p not in (s.oo,-s.oo) else [direction if direction!='both' else '+'])]
            if any(v.has(s.Limit,s.nan,s.zoo) for v in limits): raise ValueError('Limit not determined')
            ok = all(v==want or s.simplify(v-want)==0 for v in limits)
            result={'status':'verified' if ok else 'incorrect','detail':'Limit checked from both sides.' if direction=='both' else 'One-sided limit checked.'}
        conn.send(result)
    except Exception:
        conn.send({'status':'undetermined','detail':'Unsupported, ambiguous, undefined, or overly complex input; needs human review.'})
    finally: conn.close()


def _bounded(mode,args,timeout):
    if not isinstance(timeout,(float,int)) or not math.isfinite(timeout) or timeout<=0:
        return {'status':'undetermined','detail':'Verification timeout; needs human review.'}
    ctx=mp.get_context('spawn'); receiver,sender=ctx.Pipe(duplex=False)
    process=ctx.Process(target=_work,args=(sender,mode,args),daemon=True)
    try:
        process.start(); sender.close()
        if receiver.poll(min(timeout,10)):
            try: return receiver.recv()
            except EOFError: pass
        return {'status':'undetermined','detail':'Verification timed out or worker failed; needs human review.'}
    finally:
        if process.is_alive(): process.terminate()
        process.join(timeout=1); receiver.close()


def verify_answer(answer,expected,*,variables=None,domain='real',timeout=3):
    return _bounded('answer',(answer,expected,variables,domain),timeout)


def verify_limit(expression,variable,point,expected,direction='both'):
    return _bounded('limit',(expression,variable,point,expected,direction),3)


def verify_problem(question):
    return _bounded('problem',(question,),3)
