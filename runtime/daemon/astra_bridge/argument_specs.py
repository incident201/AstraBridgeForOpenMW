"""Shared declarative arguments for object-valued commands and compositions.

The gameplay validators remain authoritative for current game conditions.
These definitions also generate native-tool schemas; runners never copy them.
"""
def object_schema(properties, required=(), **extra):
    return {'type':'object','properties':properties,'additionalProperties':False,
            **({'required':list(required)} if required else {}),**extra}


def numeric(low=None, high=None, default=None):
    return {'type':'number',**({'minimum':low} if low is not None else {}),
            **({'maximum':high} if high is not None else {}),**({'default':default} if default is not None else {})}


TRIGGERS = {'Activate','ToggleWeapon','ToggleSpell','Jump','Inventory','Journal','GameMenu','Rest'}
ACTION_DEFAULTS = {'jump':8,'air_move':.5,'act':.25,'track':1,'go':12,'walk':8,'approach':30,
    'interact':30,'move_local':30,'fly':10,'evade':4,'chain':12,'wait_until':30,'sequence':60,
    'revisit':60,'return_to':60,'rest':30,'buy':30,'travel':30,'swim':30}
CLI_REQUEST_TIMEOUT = 130
LONG_ACTION_TIMEOUT = 600
ACTION_TIMEOUT_MULTIPLIER = 2
ACT_LIMITS = {'seconds':(.02,None),'move':(-1,1),'strafe':(-1,1),'yaw':(-180,180),'pitch':(-90,90)}
ACT_BOOLEANS = ('attack','run','sneak')
ACT_SCHEMA = object_schema({
    **{key:numeric(*limits) for key,limits in ACT_LIMITS.items()},
    **{key:{'type':'boolean'} for key in ACT_BOOLEANS},
    'trigger':{'type':'string','enum':sorted(TRIGGERS-{'GameMenu','Rest'})},
    'target':{'type':'string','description':'Current visible target handle, when applicable.'},
})

CHAIN_STEPS = {
    'strike':object_schema({'op':{'const':'strike'},'charge':numeric(.1,1.5,.8)},['op']),
    'cast':object_schema({'op':{'const':'cast'},'spell':{'type':'string','minLength':1,'maxLength':200},
                         'item':{'type':'string','minLength':1,'maxLength':200}},['op'],
                        **{'not':{'required':['spell','item']}}),
    'wait':object_schema({'op':{'const':'wait'},'seconds':numeric(.02,None,.5)},['op']),
}
CHAIN_MOVEMENT = object_schema({'direction':{'type':'string','enum':['forward','back','left','right']},
    'meters':numeric(.25,None,2),'run':{'type':'boolean'},'face_target':{'type':'boolean'}},['direction'])
CHAIN_SCHEMA = object_schema({'ref':{'type':'string','maxLength':100},'air':{'type':'boolean'},
    'actions':{'type':'array','minItems':1,'items':{'anyOf':list(CHAIN_STEPS.values())}},
    'max_seconds':numeric(.5,None,12),'movement':CHAIN_MOVEMENT,
    'stop_health_pct':numeric(0,100,0),'pursue':{'type':'boolean'}},['actions'])

SEQUENCE_OPS = {'jump','air_move','act','look','go','walk','revisit','return_to','approach','interact',
    'move_local','use_item','select_spell','select_enchanted','cast','strike','chain','wait_until',
    'trigger','choose','edit','adjust','focus','fly','swim','target_info','rest','buy','travel','unlock','lock'}
SEQUENCE_PROPERTIES = {'actions':{'type':'array','minItems':1},'max_seconds':numeric(.02,None,60),
    'stop_health_pct':numeric(0,100,0),'stop_on_damage':{'type':'boolean','default':True}}
SELECTOR_SCHEMA = object_schema({
    **{key:{'type':'string','minLength':1} for key in
       ('source','name','contains','kind','actor_kind','panel','role','control','instance')},
    'nearest':{'type':'boolean'},
})
SELECTOR_SCHEMA['properties']['source']['enum']=['scene','ui','inventory','spells']
SELECTOR_SCHEMA['properties']['actor_kind']['enum']=['npc','creature']
KNOWLEDGE_ACTION_FIELDS={'checkpoint':{'action','checkpoint'},'brief':{'action'}}
MAP_ARGUMENT_FIELDS={None:set(),'local':set(),'world':set(),'view':set(),'center':set(),
    'markers':set(),'close':set(),'pan':{'dx','dy'},'zoom':{'factor','fit'}}
EXPECT_SCHEMA = object_schema({'ui_mode':{'type':'string','minLength':1},
    'location':{'type':'string','minLength':1},'location_changed':{'type':'boolean'},
    'outcome':{'type':'string','minLength':1},'gold_delta':numeric(-1e12,1e12),
    'min_horizontal_displacement_m':numeric(0),
    'inventory_delta':object_schema({'name':{'type':'string','minLength':1},'delta':{'type':'integer'}},['name','delta'])})

CHECKPOINT_SCHEMA = object_schema({'goal':{'type':'string','minLength':1,'maxLength':2000},
    'next_step':{'type':'string','maxLength':2000},'status':{'type':'string','enum':['open','done','abandoned'],'default':'open'},
    **{key:{'type':'array','maxItems':8,'uniqueItems':True,'items':{'type':'string','maxLength':200,'pattern':pattern}}
       for key,pattern in {'evidence_refs':'^evidence_','note_refs':'^note_','object_refs':'^object_',
                           'place_refs':'^(node_|place_)'}.items()},
    'failed_attempts':{'type':'array','maxItems':8,'items':{'type':'string','minLength':1,'maxLength':600}}},
    ['goal','next_step'])

COMMAND_DESCRIPTIONS = {
    'status':'Read controller/action status; player=true reads your character without taking a screenshot.',
    'observe':'Observe the current player-visible scene, UI, navigation affordances and screenshot.',
    'stop':'Interrupt active input and pause. It does not save or close the game.',
    'saves':'List available save slots with fresh opaque handles.',
    'new-game':'Start normal character creation. Discards unsaved progress.',
    'record-start':'Start the existing gameplay recorder.', 'record-stop':'Finalize the existing recording.',
    'record-status':'Read recording status and encoder/frame diagnostics.',
    'scan':'Observe four camera directions using normal player turns. May stop on damage or blocking UI.',
    'ui':'Read the current UI controls and displayed text; search or page populated rows.',
    'route':'Read remembered route information.', 'unlock':'Release a camera/target lock; this does not unlock doors.',
    'survey':'Refresh nearby collision-based movement affordances. Does not expose a raw world map.',
    'ground':'List visible, bounded movement targets on reachable ground.',
    'details':'Expand a section of the latest public observation without taking a new screenshot.',
    'action-result':'Recover an existing action receipt and its diagnostics without repeating the action.',
    'autosave':'Inspect or configure the existing legal-boundary autosave ring.',
    'finish-session':'Interrupt, save, finalize recording and close. Keeps the game open if saving fails.',
    'knowledge':'Read or write this profile\'s evidence, notes, object memories and working checkpoint.',
    'read':'Read or search the currently opened book or scroll. Unopened books are not exposed.',
    'repair':'Use an owned hammer through the normal repair UI, with bounded attempts.',
    'resetNPC':'Emergency ResetActors recovery for an observed placement malfunction. Follow the skill restrictions.',
    'act':'Perform bounded normal movement/input, then pause and return its actual result.',
    'look':'Turn the player camera to a heading/pitch with normal controls.',
    'chain':'Execute a declared combat chain with ordinary game rules and interruption guards.',
    'sequence':'Execute declared predictable actions with fresh selectors, expectations and stopping guards.',
    'rest':'Use the ordinary rest/wait menu for the selected number of hours.',
    'buy':'Buy an observed barter item with quantity and price guards through normal UI.',
    'travel':'Select an observed destination from the open travel service and pay its quoted price.',
    'wait-until':'Advance bounded game time until the selected observable condition or an interruption.',
    'atlas':'Read this profile\'s learned routes, visited nodes and transitions.',
    'revisit':'Return to a remembered atlas node using learned routes and ordinary movement.',
    'inspect':'Inspect your character, inventory, spells, journal, dialogue history or other public player information.',
    'strike':'Attempt a normal melee/ranged attack at a visible target, or explicitly into empty space.',
    'cast':'Attempt a normal cast with the currently selected spell/item at a visible target or into empty space.',
    'use-item':'Use an owned inventory item by its current opaque handle.',
    'select-spell':'Select a known spell by its current opaque handle.',
    'select-enchanted':'Select an owned enchanted item by its current opaque handle.',
    'load':'Load a freshly listed save. Discards unsaved progress and invalidates transient handles.',
    'focus':'Aim the normal camera at a visible object.',
    'approach':'Approach a visible target with bounded navigation assistance and normal movement.',
    'choose':'Invoke an enabled current UI control by handle or unambiguous displayed caption.',
    'lock':'Keep the camera tracking a visible target; this does not operate door locks.',
    'hover':'Show the normal tooltip of a current on-screen UI control.',
    'target-info':'Read permitted details and reach information for a current visible target.',
    'walk':'Walk toward a current movement handle, or a point in the current ordinary screenshot.',
    'pick':'Identify a visible target near a point in the current ordinary screenshot.',
    'go':'Move to a current bounded movement affordance with an explicit time budget.',
    'return-to':'Return to an explicitly remembered place via its learned atlas connection.',
    'evade':'Attempt bounded lateral/backward evasion with normal controls.',
    'retreat':'Attempt bounded backward retreat with normal controls.',
    'save':'Create a normal save when the game permits it.',
    'edit':'Replace a current visible UI input; does not submit its confirmation.',
    'adjust':'Set a current UI slider to a valid reported position.',
    'trigger':'Invoke an allowed normal game action or menu.',
    'interact':'Activate a visible object through normal reach/focus rules, optionally approaching it.',
    'move-local':'Move by bounded player-relative distances with normal collision/navigation checks.',
    'fly':'Move normally while levitation is available; it does not grant levitation.',
    'swim':'Move normally while swimming, including vertical steering.',
    'fov':'Set the supported normal camera field of view.',
    'track':'Follow a visible target with bounded normal movement and optional attack input.',
    'remember':'Record a grounded place note in this profile\'s persistent travel memory.',
    'recall':'Search this profile\'s recorded place notes.',
    'connect':'Record an observed connection between remembered places; this is travel memory, not agent ownership.',
    'click':'Click a current ordinary screenshot point in the open game UI, with an observation guard.',
    'key':'Send an allowed UI key with an observation guard. No arbitrary key chords or console.',
    'text':'Type text into the currently focused game UI input with an observation guard.',
    'scroll':'Scroll the native UI cursor\'s current region with an observation guard.',
    'map':'View the ordinary game map, select local/world, pan/zoom, center or read visible labels.',
    'comment':'Publish optional spectator commentary without advancing gameplay.',
}
