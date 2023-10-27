from ....types import EHOffsetType

FUNC_INFO_MEMBERS = [
    ('unsigned int', 'magicNumber'),
    ('int', 'maxState'),
#     (EHOffsetType[UnwindMapEntry], 'pUnwindMap'),
    ('unsigned int', 'nTryBlocks'),
#     (EHOffsetType[TryBlockMapEntry], 'pTryBlockMap'),
    ('unsigned int', 'nIPMapEntries'),
    (EHOffsetType['void'], 'pIPtoStateMap'),
]
