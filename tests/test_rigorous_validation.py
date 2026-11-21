"""Independent closed-form and input-boundary checks for the native solver."""
import json
import math
import numpy as np
import pytest
from almond_mcp import frame_solver as fs, native_structure as ns, floor_loads as fl

@pytest.mark.parametrize('seed', range(60))
def test_randomized_cantilever_against_vector_closed_form(seed):
    rng=np.random.default_rng(seed)
    d=rng.normal(size=3); d/=np.linalg.norm(d)
    L=float(rng.uniform(.5,12)); origin=rng.uniform(-100,100,size=3)
    D=float(rng.uniform(80,300)); sec=fs.chs(D,D*.04); mat=fs.material('Steel')
    force=rng.uniform(-50,50,size=3); torque=float(rng.uniform(-4,4))
    f=fs.Frame(); n=int(rng.choice([1,2,5]))
    ids=[f.add_node(origin+d*L*i/n) for i in range(n+1)]
    for a,b in zip(ids,ids[1:]): f.add_element(a,b,sec,mat)
    f.fix(ids[0]); f.load(ids[-1],**dict(zip(['fx','fy','fz','mx','my','mz'],[*force,*(torque*d)])))
    out=fs.solve(f)
    axial=np.dot(force,d)*d; transverse=force-axial
    expected=axial*L/(mat.E*sec.A)+transverse*L**3/(3*mat.E*sec.Iy)
    rotation=np.cross(d,transverse)*L**2/(2*mat.E*sec.Iy)+torque*d*L/(mat.G*sec.J)
    np.testing.assert_allclose(out.displacements[-1,:3],expected,rtol=1e-8,atol=1e-10)
    np.testing.assert_allclose(out.displacements[-1,3:],rotation,rtol=1e-8,atol=1e-10)
    np.testing.assert_allclose(out.reactions[0,:3],-force,rtol=1e-8,atol=1e-8)
    np.testing.assert_allclose(out.reactions[0,3:],-np.cross(d*L,force)-torque*d,rtol=1e-8,atol=1e-8)
    assert out.equilibrium_error()<1e-6

def beam_model():
    return {'members':[{'source_guids':['beam'], 'points':[[0,0,0],[4,0,0]]}],
            'anchor_points':[[0,0,0]], 'tolerance_m':.001,'max_member_span_m':4,'max_span_m':4,'warnings':[]}

def test_valid_native_parameters_have_a_finite_successful_result():
    out=ns.validate(beam_model(),'beam',load_kn=.1,self_weight=False,stability='off',design_basis='unfactored')
    assert out['status']=='pass' and out['passed']
    json.dumps(out,allow_nan=False)

@pytest.mark.parametrize('field,value',[(k,v) for k in ['load_kn','limit_ratio','span_m','diameter_mm','wall_mm'] for v in [math.nan, math.inf, -math.inf]])
def test_native_validation_rejects_nonfinite_parameters(field,value):
    kwargs={'load_kn':1, 'self_weight':False,'stability':'off','design_basis':'unfactored'}
    kwargs[field]=value
    out=ns.validate(beam_model(),'beam',**kwargs)
    assert out['status']=='error' and not out['passed'],out
    json.dumps(out,allow_nan=False)

@pytest.mark.parametrize('field,value',[('span_m',-1),('limit_ratio',-250),('limit_ratio',0),('load_kn',-1),('load_kn',None),('load_kn',True)])
def test_native_validation_rejects_nonpositive_explicit_design_limits(field,value):
    kwargs={'load_kn':1,'self_weight':False,'stability':'off','design_basis':'unfactored',field:value}
    out=ns.validate(beam_model(),'beam',**kwargs)
    assert out['status']=='error' and not out['passed'],out

@pytest.mark.parametrize('shape,args',[
    ('rect',(-100,-200)),('rect',(100,-200)),('rect',(100,0)),('rect',(math.inf,200)),('rect',(math.nan,200)),
    ('i_section',(300,150,7,160)),('i_section',(300,150,160,10)),('i_section',(300,150,-7,10)),
    ('i_section',(math.inf,150,7,10)),('i_section',(300,math.nan,7,10)),
    ('chs',(math.inf,4)),('rhs',(math.inf,100,4)),('rhs',(200,math.inf,4))])
def test_invalid_section_geometry_is_rejected(shape,args):
    with pytest.raises(ValueError): getattr(fs,shape)(*args)

@pytest.mark.parametrize('field,value',[(k,v) for k in ['imposed_kn_m2','dead_kn_m2'] for v in [math.nan,math.inf,-math.inf,-1]])
def test_floor_load_input_is_rejected_before_mutating_geometry(field,value):
    frame=fs.Frame()
    with pytest.raises(ValueError):fl.apply(frame,**{field:value})
    assert not frame.nodes and not frame.elements and not frame.member_loads

@pytest.mark.parametrize('field,value',[(k,v) for k in ['max_span_m','max_member_span_m','tolerance_m'] for v in [math.nan,math.inf,-math.inf]])
def test_native_model_measurements_cannot_bypass_limits(field,value):
    m=beam_model();m[field]=value
    out=ns.validate(m,'beam',load_kn=.1,self_weight=False,stability='off',design_basis='unfactored')
    assert out['status']=='error' and not out['passed'],out

@pytest.mark.parametrize('operation',['node','load','udl','linear_load'])
@pytest.mark.parametrize('value',[math.nan,math.inf,-math.inf])
def test_solver_rejects_nonfinite_vectors_at_input(operation,value):
    frame=fs.Frame()
    a=frame.add_node([0,0,0]);b=frame.add_node([4,0,0]);frame.add_element(a,b,fs.chs(114.3,4),fs.material('Steel'))
    with pytest.raises(ValueError):
        if operation=='node':frame.add_node([value,0,0])
        if operation=='load':frame.load(b,fz=value)
        if operation=='udl':frame.udl(0,[value,0,0])
        if operation=='linear_load':frame.linear_load(0,[0,0,0],[value,0,0])

@pytest.mark.parametrize('gamma_m1',[1.1,1.25,1.5])
def test_member_buckling_uses_nondefault_safety_factor(gamma_m1):
    sec=fs.chs(114.3,4);mat=fs.material('Steel');L=4.;N=100.
    frame=fs.Frame(gamma_m=(1.,gamma_m1))
    a=frame.add_node([0,0,0]);b=frame.add_node([L,0,0]);frame.add_element(a,b,sec,mat)
    frame.fix(a,(True,True,True,True,False,False));frame.fix(b,(False,True,True,False,False,False));frame.load(b,fx=-N)
    out=fs.solve(frame)
    lam=math.sqrt(sec.A*mat.fy/(math.pi**2*mat.E*sec.Iy/L**2))
    phi=.5*(1+.21*(lam-.2)+lam**2)
    chi=1/(phi+math.sqrt(phi**2-lam**2))
    assert out.elements[0].util_detail['buckling']==pytest.approx(N*gamma_m1/(chi*sec.A*mat.fy),rel=1e-10)

def test_default_member_table_sag_excludes_common_support_settlement():
    sec=fs.chs(193.7,8);mat=fs.material('Steel');L=4.;w=2.;k=100.
    frame=fs.Frame();ids=[frame.add_node([i*L/2,0,3]) for i in range(3)]
    for a,b in zip(ids,ids[1:]):
        frame.add_element(a,b,sec,mat,tag=['spring-beam']);frame.udl(len(frame.elements)-1,[0,0,-w])
    frame.fix(ids[0],(True,True,False,True,False,False));frame.fix(ids[-1],(False,True,False,False,False,False))
    frame.spring(ids[0],kz=k);frame.spring(ids[-1],kz=k)
    result=fs.solve(frame)
    model={'members':[{'source_guids':['spring-beam']}]}
    rows=ns.member_table(model,frame,result,[(er.utilization,'unfactored',er) for er in result.elements])
    expected_sag=5*w*L**4/(384*mat.E*sec.Iy)
    assert result.displacements[ids[0],2]==pytest.approx(-w*L/(2*k),rel=1e-9)
    assert result.max_displacement>10*expected_sag
    assert rows[0]['deflection_mm']==pytest.approx(expected_sag*1000,abs=.00051)
