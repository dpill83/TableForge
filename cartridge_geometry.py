"""Read-only cartridge geometry v1 validation; no state or visibility is inferred."""
import math

EPS = 1e-6

def point(p):
    return isinstance(p, dict) and all(type(p.get(k)) in (int, float) and math.isfinite(p[k]) for k in ('xFt', 'yFt'))

def distance(a, b):
    return math.hypot(a['xFt'] - b['xFt'], a['yFt'] - b['yFt'])

def same(a, b):
    return point(a) and point(b) and distance(a, b) < EPS

def cross(a, b, c):
    return (b['xFt']-a['xFt'])*(c['yFt']-a['yFt'])-(b['yFt']-a['yFt'])*(c['xFt']-a['xFt'])

def on_segment(p, a, b):
    return (all(point(x) for x in (p, a, b)) and abs(cross(a, b, p)) < EPS
            and min(a['xFt'], b['xFt'])-EPS <= p['xFt'] <= max(a['xFt'], b['xFt'])+EPS
            and min(a['yFt'], b['yFt'])-EPS <= p['yFt'] <= max(a['yFt'], b['yFt'])+EPS)

def intersects(a, b, c, d):
    return (on_segment(a,c,d) or on_segment(b,c,d) or on_segment(c,a,b) or on_segment(d,a,b)
            or (cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0))

def inside(p, outline):
    if not point(p):
        return False
    result = False
    for s in outline:
        a,b = s['from'],s['to']
        if on_segment(p,a,b):
            return True
        if (a['yFt'] > p['yFt']) != (b['yFt'] > p['yFt']) and p['xFt'] < (b['xFt']-a['xFt'])*(p['yFt']-a['yFt'])/(b['yFt']-a['yFt'])+a['xFt']:
            result = not result
    return result

def contained_footprint(points, outline):
    if not isinstance(points,list) or len(points)<3 or any(not inside(p,outline) for p in points):
        return False
    area=0
    for i,a in enumerate(points):
        b=points[(i+1)%len(points)]
        if same(a,b):
            return False
        area+=a['xFt']*b['yFt']-b['xFt']*a['yFt']
        length=distance(a,b)
        cuts=[0,1]
        for segment in outline:
            c,d=segment['from'],segment['to']
            if cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0:
                return False
            if on_segment(c,a,b):
                cuts.append(distance(a,c)/length)
        cuts.sort()
        for j in range(1,len(cuts)):
            t=(cuts[j-1]+cuts[j])/2
            if not inside({'xFt':a['xFt']+(b['xFt']-a['xFt'])*t,'yFt':a['yFt']+(b['yFt']-a['yFt'])*t},outline):
                return False
        for j in range(i+2,len(points)):
            if i==0 and j==len(points)-1:
                continue
            if intersects(a,b,points[j],points[(j+1)%len(points)]):
                return False
    return abs(area)>EPS

def _validate(data):
    """Return actionable errors; geometry-free legacy data is valid."""
    errors = []
    rooms = data.get('rooms', [])
    enabled = ('geometryVersion' in data or 'connections' in data or isinstance(rooms,list) and any(
        isinstance(r,dict) and ('geometry' in r or any(isinstance(e,dict) and 'connectionId' in e
        for e in (r.get('exits') or r.get('doorways') or []) if isinstance(e,dict))) for r in rooms))
    if not enabled:
        return []
    if type(data.get('geometryVersion')) is not int or data['geometryVersion'] != 1:
        errors.append('geometryVersion must be 1')
    connections = data.get('connections')
    if not isinstance(connections,list):
        errors.append('connections must be an array')
        connections = []
    if not isinstance(rooms,list):
        return errors + ['Geometry requires rooms']
    by_number, boundaries = {}, {}
    for r in rooms:
        if not isinstance(r,dict):
            errors.append('Invalid geometry room')
            continue
        n = r.get('roomNumber')
        if type(n) is not int or n in by_number:
            errors.append('Invalid/duplicate geometry room number')
            continue
        by_number[n] = r
        g = r.get('geometry')
        outline = g.get('outline') if isinstance(g,dict) else None
        if not isinstance(outline,list) or len(outline)<3 or any(not isinstance(s,dict)
                or not isinstance(s.get('id'),str) or not s['id'] or not point(s.get('from'))
                or not point(s.get('to')) or same(s['from'],s['to'])
                or not isinstance(outline[(i+1)%len(outline)],dict)
                or not same(s['to'],outline[(i+1)%len(outline)].get('from')) for i,s in enumerate(outline)):
            errors.append(f'Room {n}: outline must be closed with named nonzero segments')
            continue
        segments = {s['id']:s for s in outline}
        if len(segments)!=len(outline):
            errors.append(f'Room {n}: duplicate boundary IDs')
        if abs(sum(s['from']['xFt']*s['to']['yFt']-s['to']['xFt']*s['from']['yFt'] for s in outline))<EPS:
            errors.append(f'Room {n}: outline has no area')
        for i,a in enumerate(outline):
            for j in range(i+1,len(outline)):
                if j==i+1 or (i==0 and j==len(outline)-1):
                    continue
                b=outline[j]
                if intersects(a['from'],a['to'],b['from'],b['to']):
                    errors.append(f'Room {n}: outline intersects itself')
        boundaries[n]=segments
        features=g.get('features')
        if not isinstance(features,list):
            errors.append(f'Room {n}: features must be an array')
            continue
        ids=set()
        for f in features:
            if not isinstance(f,dict) or not isinstance(f.get('id'),str) or not f['id'] or f['id'] in ids:
                errors.append(f'Room {n}: invalid/duplicate feature ID')
                continue
            ids.add(f['id'])
            if not isinstance(f.get('type'),str) or not f['type']:
                errors.append(f'Room {n}: feature needs type')
            if f.get('position') is not None and not inside(f['position'],outline):
                errors.append(f'Room {n}: feature position outside boundary')
            footprint=f.get('footprint')
            if footprint is not None and not contained_footprint(footprint,outline):
                errors.append(f'Room {n}: feature footprint outside boundary')
    ids=set()
    for c in connections:
        if not isinstance(c,dict) or not isinstance(c.get('id'),str) or not c['id'] or c['id'] in ids:
            errors.append('Invalid/duplicate connection ID')
            continue
        ids.add(c['id'])
        ends=c.get('endpoints')
        if not isinstance(ends,list) or len(ends)!=2 or any(not isinstance(e,dict) for e in ends) or ends[0].get('roomNumber')==ends[1].get('roomNumber'):
            errors.append(f"{c['id']}: needs two distinct endpoints")
            continue
        for i,e in enumerate(ends):
            n=e.get('roomNumber')
            if n is None and e.get('outside') is True:
                continue
            r=by_number.get(n) if type(n) is int else None
            segment=boundaries.get(n,{}).get(e.get('boundaryId')) if r and isinstance(e.get('boundaryId'),str) else None
            if not segment or not on_segment(e.get('position'),segment['from'],segment['to']):
                errors.append(f"{c['id']}: invalid endpoint in room {n}")
                continue
            width=e.get('widthFt')
            length=distance(segment['from'],segment['to'])
            along=distance(e['position'],segment['from'])
            if type(width) not in (int,float) or not math.isfinite(width) or width<=0 or along-width/2 < -EPS or along+width/2>length+EPS:
                errors.append(f"{c['id']}: opening extends beyond boundary")
            if not isinstance(e.get('description'),str) or not e['description'].strip():
                errors.append(f"{c['id']}: endpoint needs description")
            exits=r.get('exits') or r.get('doorways') or []
            matches=[x for x in exits if isinstance(x,dict) and x.get('connectionId')==c['id']]
            other=ends[1-i]
            if len(matches)!=1 or (other['roomNumber'] is None and matches[0].get('exitsDungeon') is not True) or (other['roomNumber'] is not None and matches[0].get('connectsTo')!=other['roomNumber']):
                errors.append(f"{c['id']}: Room {n} needs one matching reciprocal exit")
            outline=r['geometry']['outline']
            area=sum(s['from']['xFt']*s['to']['yFt']-s['to']['xFt']*s['from']['yFt'] for s in outline)
            winding=1 if area>0 else -1
            dx=segment['to']['xFt']-segment['from']['xFt']
            dy=segment['to']['yFt']-segment['from']['yFt']
            direction=('east' if dy*winding>0 else 'west') if abs(dx)<EPS else (('south' if -dx*winding>0 else 'north') if abs(dy)<EPS else None)
            if direction and len(matches)==1 and matches[0].get('direction')!=direction:
                errors.append(f"{c['id']}: Room {n} exit direction disagrees with boundary")

    for n,r in by_number.items():
        for e in r.get('exits') or r.get('doorways') or []:
            c=next((c for c in connections if isinstance(c,dict) and isinstance(e,dict) and c.get('id')==e.get('connectionId')),None)
            if not c or not any(isinstance(p,dict) and p.get('roomNumber')==n for p in c.get('endpoints',[]) if isinstance(p,dict)):
                errors.append(f'Room {n}: unknown connection')
    return errors


def arrival_endpoint(data, location, connection_id):
    if location is None or not isinstance(connection_id,str):
        return None
    for c in data.get('connections',[]):
        if c['id']==connection_id:
            return next((e for e in c['endpoints'] if e['roomNumber']==location),None)
    return None


def validate(data):
    try:
        return _validate(data)
    except (TypeError, KeyError, AttributeError, ValueError, IndexError):
        return ['Malformed geometry: check rooms, outlines, features, exits and endpoints']
