from typing import Optional
import binaryninja as bn
from .var import CheckedTypeDataVar
from .annotation import DisplacementOffset, Array

class RelativeOffsetListener(bn.BinaryDataNotification):
    def __init__(self):
        super().__init__(
            bn.NotificationType.NotificationBarrier |
            bn.NotificationType.DataVariableAdded |
            bn.NotificationType.DataVariableLifetime |
            bn.NotificationType.DataVariableRemoved |
            bn.NotificationType.DataVariableUpdated |
            bn.NotificationType.DataVariableUpdates
        )
        self.received_event = False

    def notification_barrier(self, view: bn.BinaryView) -> int:
        has_events = self.received_event
        self.received_event = False

        if has_events:
            return 250

        return 0

    def find_checked_type(self, view: bn.BinaryView, _type: bn.Type) \
        -> Optional[type[CheckedTypeDataVar]]:
        if isinstance(_type, bn.NamedTypeReferenceType):
            return next(
                (
                    scls
                    for scls in CheckedTypeDataVar.__subclasses__()
                    if scls.get_typedef_ref(view) == _type
                ),
                None,
            )

        if isinstance(_type, bn.StructureType):
            if len(_type.base_structures) != 1:
                return None

            base = _type.base_structures[0].type
            return next(
                (
                    scls
                    for scls in CheckedTypeDataVar.__subclasses__()
                    if scls.alt_name == base.name
                ),
                None,
            )

        return None

    def data_var_added(self, view: bn.BinaryView, var: bn.DataVariable) -> None:
        self.received_event = True
        if (var_type := self.find_checked_type(view, var.type)) is None:
            return

        for name, mtype in var_type.member_map.items():
            if (offset_type := DisplacementOffset.get_origin(mtype)) is not None:
                view.add_user_data_ref(
                    var[name].address,
                    offset_type.resolve_offset(view, var[name].value)
                )
            elif (offset_type := DisplacementOffset.get_origin(Array.get_element_type(mtype))) is not None:
                for element in var[name]:
                    view.add_user_data_ref(
                        element.address,
                        offset_type.resolve_offset(view, element.value)
                    )

        for name, mtype in var_type.virtual_relative_members.items():
            if not any(member.name == name for member in var.type.members):
                continue

            if (offset_type := DisplacementOffset.get_origin(mtype)) is not None:
                view.add_user_data_ref(
                    var[name].address,
                    offset_type.resolve_offset(view, var[name].value)
                )
            elif (offset_type := DisplacementOffset.get_origin(Array.get_element_type(mtype))) is not None:
                for element in var[name]:
                    view.add_user_data_ref(
                        element.address,
                        offset_type.resolve_offset(view, element.value)
                    )

    def data_var_updated(self, view: bn.BinaryView, var: bn.DataVariable) -> None:
        self.received_event = True
        if (var_type := self.find_checked_type(view, var.type)) is None:
            return

        for name, mtype in var_type.member_map.items():
            if (offset_type := DisplacementOffset.get_origin(mtype)) is not None:
                view.add_user_data_ref(
                    var[name].address,
                    offset_type.resolve_offset(view, var[name].value)
                )
            elif (offset_type := DisplacementOffset.get_origin(Array.get_element_type(mtype))) is not None:
                for element in var[name]:
                    view.add_user_data_ref(
                        element.address,
                        offset_type.resolve_offset(view, element.value)
                    )

        for name, mtype in var_type.virtual_relative_members.items():
            if (offset_type := DisplacementOffset.get_origin(mtype)) is not None:
                view.add_user_data_ref(
                    var[name].address,
                    offset_type.resolve_offset(view, var[name].value)
                )
            elif (offset_type := DisplacementOffset.get_origin(Array.get_element_type(mtype))) is not None:
                for element in var[name]:
                    view.add_user_data_ref(
                        element.address,
                        offset_type.resolve_offset(view, element.value)
                    )

    def data_var_removed(self, view: bn.BinaryView, var: bn.DataVariable) -> None:
        self.received_event = True
        if (var_type := self.find_checked_type(view, var.type)) is None:
            return

        for name, mtype in var_type.member_map.items():
            if (offset_type := DisplacementOffset.get_origin(mtype)) is not None:
                view.remove_user_data_ref(
                    var[name].address,
                    offset_type.resolve_offset(view, var[name].value)
                )
            elif (offset_type := DisplacementOffset.get_origin(Array.get_element_type(mtype))) is not None:
                for element in var[name]:
                    view.remove_user_data_ref(
                        element.address,
                        offset_type.resolve_offset(view, element.value)
                    )

        for name, mtype in var_type.virtual_relative_members.items():
            if (offset_type := DisplacementOffset.get_origin(mtype)) is not None:
                view.remove_user_data_ref(
                    var[name].address,
                    offset_type.resolve_offset(view, var[name].value)
                )
            elif (offset_type := DisplacementOffset.get_origin(Array.get_element_type(mtype))) is not None:
                for element in var[name]:
                    view.remove_user_data_ref(
                        element.address,
                        offset_type.resolve_offset(view, element.value)
                    )
