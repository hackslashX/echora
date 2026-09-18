/** Ray-marched smoke, with front-to-back extinction and short light probes. */
export const cloudFragmentShader = `
precision highp float;
varying vec2 vUv;
uniform vec2 resolution;
uniform vec3 tint;
uniform float travel, bass, mid, treble, glow, strike, seed;
float hash(vec3 p) {
  p = fract(p * .3183099 + vec3(.11,.27,.43));
  p *= 17.0;
  return fract(p.x*p.y*p.z*(p.x+p.y+p.z));
}
float noise(vec3 p) {
  vec3 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
  return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),
    mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
    mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),
    mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);
}
float fbm(vec3 p) {
  float n=0.0, a=.53;
  for(int i=0;i<5;i++) { n+=a*noise(p); p=p*2.03+vec3(11.7,3.1,7.9); a*=.48; }
  return n;
}
float density(vec3 p) {
  p += vec3(travel*.34, -travel*.09, travel*.12);
  float fold=noise(p*.65+vec3(0,0,travel*.035));
  // A nonzero haze floor fills every pixel. No horizon or isolated cloud sprites.
  return .09 + smoothstep(.23,.78,fbm(p*1.65+fold*(1.8+bass*.28)))*(1.5+bass*.85);
}
float boltX(float y) {
  float cell=y*23.0;
  float jag=mix(hash(vec3(floor(cell),seed,1)),hash(vec3(floor(cell)+1.0,seed,1)),fract(cell));
  return (hash(vec3(seed,2,1))-.5)*1.7 + (jag-.5)*.13 + sin(y*6.0+seed)*.09;
}
void main() {
  vec2 uv=(vUv-.5)*vec2(resolution.x/resolution.y,1.0);
  vec3 ray=normalize(vec3(uv*.95,1.25));
  vec3 color=vec3(0.0);
  float trans=1.0;
  // Midpoint samples avoid visible screen-space grain in the enlarged backdrop.
  vec3 pigment=clamp(tint,0.0,1.0);
  pigment/=max(.25,max(pigment.r,max(pigment.g,pigment.b)));
  vec3 cloudLight=mix(vec3(.78,.81,.84),pigment,.55);
  vec3 lightPos=vec3((hash(vec3(seed,2,1))-.5)*4.0,.6,2.1);
  for(int i=0;i<48;i++) {
    float t=(float(i)+.5)*.09;
    vec3 p=vec3(uv*.9,-.6)+ray*t;
    float d=density(p);
    float shade=exp(-density(p+vec3(-.35,.42,-.24))*1.25);
    float rim=clamp((d-density(p+vec3(-.12,.17,-.08)))*2.0,0.0,1.0);
    // Neutral charcoal stays neutral. Album pigment belongs to lit folds,
    // not a multiplication across every shadow and highlight.
    vec3 smoke=mix(vec3(.016,.019,.024),vec3(.12,.13,.145),shade);
    smoke += cloudLight*rim*(.07+treble*.17);
    smoke += cloudLight*pow(shade,2.0)*mid*.12;
    smoke *= .95+bass*.15;
    float distanceToLight=length(p-lightPos);
    float scattered=exp(-distanceToLight*distanceToLight*.65);
    smoke += mix(cloudLight,vec3(.78,.83,.88),.35)*glow*scattered*.40;
    smoke += vec3(.70,.77,.84)*strike*scattered*.45;
    float alpha=1.0-exp(-d*.09*1.6);
    color+=trans*alpha*smoke;
    trans*=1.0-alpha;
    if(trans<.015) break;
  }
  color+=trans*vec3(.015,.019,.026);
  // Branching lightning sits inside the mist, never a full-screen white flash.
  float y=vUv.y;
  float x=boltX(y);
  float line=abs(uv.x-x);
  float branchY=clamp((.59-y)/.32,0.0,1.0);
  float branch=abs(uv.x-(boltX(.59)+branchY*.27+sin(y*65.0+seed)*.012));
  float branchMask=smoothstep(.24,.30,y)*(1.0-smoothstep(.56,.60,y));
  float bolt=exp(-line*620.0)+exp(-line*55.0)*.22;
  bolt+=(exp(-branch*580.0)*.6+exp(-branch*65.0)*.12)*branchMask;
  bolt*=smoothstep(.10,.24,y)*(1.0-smoothstep(.82,.97,y));
  color+=vec3(.46,.53,.64)*bolt*strike;
  color*=1.0-.14*dot(vUv-.5,vUv-.5);
  // Soft highlight rolloff preserves hue when lighting responses overlap.
  color=color/(vec3(1.0)+color*.65);
  gl_FragColor=vec4(color,1.0);
}
`;
