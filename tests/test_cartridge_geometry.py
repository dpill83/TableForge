"""Bidirectional contract and HTTP save/resume tests; no paid AI calls."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import ai
import cartridge_geometry as geometry
import module_context
import server
import test_flow

FIXTURE = json.loads((Path(__file__).parent/'fixtures/bidirectional-geometry.json').read_text(encoding='utf-8'))
MODULE = '# Geometry fixture\n## Areas\n' + ''.join(f'### Area {r["roomNumber"]}: Chamber\nRoom description.\n' for r in FIXTURE['rooms'])

class ContractTest(unittest.TestCase):
    def test_fixture_and_reverse_traversal(self):
        self.assertEqual(geometry.validate(FIXTURE), [])
        for n, x, y in [(9,2.5,0),(4,52.5,20)]:
            e=geometry.arrival_endpoint(FIXTURE,n,'south-east-opening')
            self.assertEqual(e['position'],{'xFt':x,'yFt':y})
        self.assertIsNone(geometry.arrival_endpoint(FIXTURE,12,'south-east-opening'))
        reverse=copy.deepcopy(FIXTURE)
        reverse['rooms'].reverse()
        for c in reverse['connections']: c['endpoints'].reverse()
        self.assertEqual(geometry.validate(reverse), [])

    def test_malformed_contract_and_legacy(self):
        for mutate in [lambda d:d['connections'][0]['endpoints'].pop(),
                       lambda d:d['connections'][0]['endpoints'][1].update(boundaryId='missing'),
                       lambda d:d['connections'][0]['endpoints'][1].update(widthFt=120),
                       lambda d:d['rooms'][0]['exits'].pop(),
                       lambda d:d['rooms'][0]['exits'][0].update(connectsTo=12),
                       lambda d:d['rooms'][0]['exits'][0].update(direction='east'),
                       lambda d:d['rooms'][1]['geometry']['features'][0]['position'].update(xFt=100),
                       lambda d:d['rooms'][2]['geometry']['features'].append({'id':'bad','type':'altar','position':{'xFt':20,'yFt':20}}),
                       lambda d:d['rooms'][0]['geometry']['outline'][0]['to'].update(xFt=99),
                       lambda d:d['rooms'][2]['geometry']['features'].append({'id':'crossing','type':'altar','footprint':[{'xFt':25,'yFt':5},{'xFt':5,'yFt':25},{'xFt':5,'yFt':5}]}),
                       lambda d:d.update(connections={})]:
            data=copy.deepcopy(FIXTURE); mutate(data)
            self.assertTrue(geometry.validate(data))
            with self.assertRaisesRegex(ValueError,'Invalid cartridge geometry'):
                module_context.Adventure(MODULE,data)
        self.assertEqual(geometry.validate({'rooms':[{'roomNumber':1}]}),[])

    def test_marker_only_uses_last_location_and_never_leaks_arrival(self):
        text='Narration. [Location: Area 4; Arrival: south-east-opening]'
        self.assertEqual(module_context.take_arrival(text),(True,'south-east-opening'))
        self.assertEqual(module_context.take_marker(text),('Narration.',True,4))
        self.assertEqual(module_context.take_arrival(text+' [Location: Area 9]'),(False,None))
        self.assertEqual(module_context.take_arrival('[Location: Area 4; Arrival: unknown]'),(True,None))

    def test_focused_context_keeps_complete_endpoints_without_remote_room_prose(self):
        adventure=module_context.Adventure(MODULE,FIXTURE)
        _, focus=adventure.assemble(9)
        data=adventure.structured_context(focus)
        self.assertNotIn(12,[r['roomNumber'] for r in data['rooms']])
        edge=next(c for c in data['connections'] if c['id']=='south-east-opening')
        self.assertEqual(edge,FIXTURE['connections'][0])
        self.assertIn('Arrival: connection-id',adventure.marker_instructions())

    def test_opening_arrival_includes_entrance_connections(self):
        data=copy.deepcopy(FIXTURE)
        data['hook']={'dmSecrets':'Authored opening.'}
        data['rooms'][0]['beat']='entrance'
        adventure=module_context.Adventure(MODULE,data)
        arrival=adventure.opening_data('arrival')
        self.assertEqual(arrival['geometryVersion'],1)
        self.assertEqual([r['roomNumber'] for r in arrival['rooms']],[9])
        self.assertEqual({c['id'] for c in arrival['connections']},
                         {'south-east-opening','second-opening','site-entrance'})
        entrance=next(c for c in arrival['connections'] if c['id']=='site-entrance')
        self.assertEqual(entrance,FIXTURE['connections'][3])
        for stage in ('establishing','hook','decision','travel'):
            self.assertNotIn('connections',adventure.opening_data(stage))
        legacy=module_context.Adventure(MODULE,{'hook':{'dmSecrets':'x'},'rooms':[{'roomNumber':1}]})
        self.assertNotIn('connections',legacy.opening_data('arrival'))
        self.assertNotIn('geometryVersion',legacy.opening_data('arrival'))

class GeometryFlowTest(unittest.TestCase):
    setUp=test_flow.FlowTest.setUp
    tearDown=test_flow.FlowTest.tearDown
    api=test_flow.FlowTest.api
    api_error=test_flow.FlowTest.api_error
    cartridge_zip=test_flow.FlowTest.cartridge_zip
    override=test_flow.FlowTest.override

    def new_save(self):
        cartridge=self.cartridge_zip({'manifest.json':json.dumps({'format':'tableforge-adventure','formatVersion':1,'title':'Geometry','resources':{}}),'module.md':MODULE,'run-data.json':json.dumps(FIXTURE)})
        self.assertEqual(cartridge['invalid'],{})
        state=self.api('/api/saves',{'cartridgeId':cartridge['id'],'players':[{'name':'Test','character':'Scout'}]})
        return state['save']['id']

    def advance(self,save_id,text):
        provider=test_flow.FakeProvider(text)
        with patch.object(ai,'current_provider',return_value=provider):
            self.api(f'/api/saves/{save_id}/advance',self.override(save_id))
        return self.api(f'/api/saves/{save_id}'),provider

    def test_arrival_survives_reload_context_and_reverse_traversal(self):
        save_id=self.new_save()
        state,_=self.advance(save_id,'You enter the long chamber. [Location: Area 4; Arrival: south-east-opening]')
        self.assertEqual(state['save']['location'],4)
        self.assertEqual(state['save']['arrival_connection_id'],'south-east-opening')
        self.assertNotIn('Arrival:',state['messages'][-1]['body'])
        preview=self.api(f'/api/saves/{save_id}/context')
        self.assertIn('Tracked arrival',preview['messages'][0]['content'])
        self.assertIn('52.5',preview['messages'][0]['content'])
        state,provider=self.advance(save_id,'The pillar is close to your entrance. [Location: Area 4]')
        self.assertEqual(provider.context['arrival']['endpoint']['position'],{'xFt':52.5,'yFt':20})
        self.assertEqual(state['save']['arrival_connection_id'],'south-east-opening')
        state,_=self.advance(save_id,'You return through the opening. [Location: Area 9; Arrival: south-east-opening]')
        self.assertEqual(state['save']['arrival_connection_id'],'south-east-opening')
        state,provider=self.advance(save_id,'You pause. [Location: Area 9]')
        self.assertEqual(provider.context['arrival']['endpoint']['position'],{'xFt':2.5,'yFt':0})
        state,_=self.advance(save_id,'You use the other opening. [Location: Area 4; Arrival: second-opening]')
        self.assertEqual(state['save']['arrival_connection_id'],'second-opening')
        self.assertEqual(self.api(f'/api/saves/{save_id}')['save']['arrival_connection_id'],'second-opening')
        # Summarizing away the entrance beat must not erase the stored spatial frame.
        summarized=self.api(f'/api/saves/{save_id}/summaries', {
            'playerId':state['players'][0]['id'], 'text':'The party explored the chambers.',
            'basedOn':None, 'throughMessageId':state['messages'][-1]['id']})
        self.assertEqual(summarized['save']['arrival_connection_id'],'second-opening')
        state,provider=self.advance(save_id,'You examine the long chamber. [Location: Area 4]')
        self.assertEqual(provider.context['arrival']['endpoint']['position'],{'xFt':57.5,'yFt':20})


    def test_unknown_invalid_arrivals_and_pilot_corrections(self):
        save_id=self.new_save()
        for marker,expected in [('[Location: Area 4; Arrival: south-east-opening]','south-east-opening'),
                                ('[Location: Area 4; Arrival: unknown]',None),
                                ('[Location: Area 4; Arrival: invented]',None),
                                ('[Location: Area 4; Arrival: south-east-opening]','south-east-opening'),
                                ('[Location: Area 12]',None),
                                ('[Location: Approach; Arrival: site-entrance]',None)]:
            state,_=self.advance(save_id,'You continue. '+marker)
            self.assertEqual(state['save']['arrival_connection_id'],expected)
        state,_=self.advance(save_id,'You enter. [Location: Area 4; Arrival: second-opening]')
        state=self.api(f'/api/saves/{save_id}/location',{'playerId':state['players'][0]['id'],'location':4})
        self.assertIsNone(state['save']['arrival_connection_id'])

    def test_failed_narration_does_not_change_arrival(self):
        save_id=self.new_save()
        before,_=self.advance(save_id,'You enter. [Location: Area 4; Arrival: second-opening]')
        with patch.object(ai,'current_provider',return_value=test_flow.BoomProvider()):
            self.api_error(f'/api/saves/{save_id}/advance',self.override(save_id))
        state=self.api(f'/api/saves/{save_id}')
        self.assertEqual(state['save']['location'],before['save']['location'])
        self.assertEqual(state['save']['arrival_connection_id'],'second-opening')
        # A response rejected after extracting metadata must not advance state either.
        with patch.object(ai,'current_provider',return_value=test_flow.FakeProvider('[Location: Area 9; Arrival: south-east-opening]')):
            self.api_error(f'/api/saves/{save_id}/advance',self.override(save_id))
        self.assertEqual(self.api(f'/api/saves/{save_id}')['save']['arrival_connection_id'],'second-opening')

    def test_invalid_geometry_is_reported_at_import_and_blocks_save(self):
        invalid=copy.deepcopy(FIXTURE)
        invalid['connections'][0]['endpoints'][1]['position']['xFt']=500
        cartridge=self.cartridge_zip({'manifest.json':json.dumps({'format':'tableforge-adventure','formatVersion':1,'title':'Geometry','resources':{}}),'module.md':MODULE,'run-data.json':json.dumps(invalid)})
        self.assertIn('geometry',cartridge['invalid']['run-data.json'])
        result=self.api_error('/api/saves',{'cartridgeId':cartridge['id'],'players':[{'name':'Test'}]})
        self.assertIn('Invalid cartridge bindings',result['error'])
