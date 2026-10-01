// Read-only information about the player's own equipment/magic and a Lua-validated visible target.
#pragma once
#include "object.hpp"
#include "../mwbase/environment.hpp"
#include "../mwbase/world.hpp"
#include "../mwbase/windowmanager.hpp"
#include "../mwworld/class.hpp"
#include "../mwworld/esmstore.hpp"
#include "../mwworld/inventorystore.hpp"
#include "../mwmechanics/combat.hpp"
#include "../mwmechanics/creaturestats.hpp"
#include "../mwmechanics/spells.hpp"
#include "../mwmechanics/spellutil.hpp"
#include "../mwmechanics/weapontype.hpp"
#include "../mwrender/npcanimation.hpp"
#include <components/misc/constants.hpp>
#include <components/esm3/loadweap.hpp>
#include <components/esm3/loadench.hpp>
#include <components/esm3/loadspel.hpp>
#include <components/esm3/loadmgef.hpp>
#include <components/esm3/loadlock.hpp>
#include <components/esm3/loadprob.hpp>

namespace MWLua::AstraCombat
{
    inline MWWorld::Ptr player() { return MWBase::Environment::get().getWorld()->getPlayerPtr(); }
    inline MWWorld::Ptr weapon(const MWWorld::Ptr& actor)
    {
        auto& inventory=actor.getClass().getInventoryStore(actor);
        auto it=inventory.getSlot(MWWorld::InventoryStore::Slot_CarriedRight);
        return it==inventory.end()?MWWorld::Ptr():*it;
    }
    inline sol::table spellInfo(sol::this_state state,const ESM::RefId& id)
    {
        sol::table out(sol::state_view(state),sol::create);
        const auto actor=player();
        auto& stats=actor.getClass().getCreatureStats(actor);
        // No database query for unowned spells, even if an internal caller supplies an ID.
        if (!stats.getSpells().hasSpell(id)) return out;
        const auto* spell=MWBase::Environment::get().getESMStore()->get<ESM::Spell>().find(id);
        if (spell->mData.mType!=ESM::Spell::ST_Spell && spell->mData.mType!=ESM::Spell::ST_Power) return out;
        const int cost=MWMechanics::calcSpellCost(*spell);
        const bool power=spell->mData.mType==ESM::Spell::ST_Power;
        out["name"]=spell->mName;out["kind"]=power?"power":"spell";out["cost"]=cost;
        out["success_chance"]=static_cast<int>(MWMechanics::getSpellSuccessChance(spell,actor));
        std::string why;
        if (power && !stats.getSpells().canUsePower(spell)) why="power_already_used";
        else if (!power && stats.getMagicka().getCurrent()<cost) why="insufficient_magicka";
        else if (!power && stats.getMagicEffects().getOrDefault(ESM::MagicEffect::Silence).getMagnitude()>0) why="silenced";
        out["available"]=why.empty();
        if (!why.empty()) out["unavailable_reason"]=why;
        return out;
    }
    inline sol::table projectileParameters(sol::this_state state)
    {
        sol::table out(sol::state_view(state),sol::create);out["supported"]=false;
        auto world=MWBase::Environment::get().getWorld();
        const auto actor=player(),held=weapon(actor);
        if (held.isEmpty() || held.getType()!=ESM::Weapon::sRecordId) return out;
        const auto type=held.get<ESM::Weapon>()->mBase->mData.mType;
        const bool thrown=type==ESM::Weapon::MarksmanThrown;
        if (!thrown && type!=ESM::Weapon::MarksmanBow && type!=ESM::Weapon::MarksmanCrossbow) return out;
        auto* animation=dynamic_cast<MWRender::NpcAnimation*>(world->getAnimation(actor));
        if (!animation) return out;
        osg::Node* node=thrown?animation->getWeaponNode():animation->getArrowBone();
        if (!node) return out;
        const auto paths=node->getParentalNodePaths();
        if (paths.empty()) return out;
        const osg::Vec3f origin=osg::computeLocalToWorld(paths.front()).getTrans();
        if ((origin-actor.getRefData().getPosition().asVec3()).length()>300) return out;
        const auto& gmst=MWBase::Environment::get().getESMStore()->get<ESM::GameSetting>();
        const std::string group=MWMechanics::getWeaponType(type)->mLongGroup;
        const float minimum=animation->getTextKeyTime(group+": shoot min attack");
        const float maximum=animation->getTextKeyTime(group+": shoot max attack");
        const float current=animation->getCurrentTime(group);
        out["supported"]=true;
        // Transported only to the player motor, never serialized as observation.
        out["origin"]=origin;
        out["speed_min"]=gmst.find(thrown?"fThrownWeaponMinSpeed":"fProjectileMinSpeed")->mValue.getFloat();
        out["speed_max"]=gmst.find(thrown?"fThrownWeaponMaxSpeed":"fProjectileMaxSpeed")->mValue.getFloat();
        out["gravity"]=Constants::GravityConst*Constants::UnitsPerMeter*.1f;
        out["strength"]=minimum>=0 && maximum>minimum && current>=0
            ?std::clamp((current-minimum)/(maximum-minimum),0.f,1.f):1.f;
        return out;
    }
    inline sol::table info(sol::this_state state)
    {
        sol::state_view lua(state);
        sol::table out(lua,sol::create),weaponInfo(lua,sol::create),castable(lua,sol::create);
        const auto actor=player();
        const auto held=weapon(actor);
        auto& inventory=actor.getClass().getInventoryStore(actor);
        auto wm=MWBase::Environment::get().getWindowManager();
        if (wm->isAllowed(MWGui::GW_Inventory))
        {
            weaponInfo["kind"]="unarmed";
            weaponInfo["available"]=true;
            if (!held.isEmpty())
            {
                weaponInfo["name"]=std::string(held.getClass().getName(held));
                if (held.getType()==ESM::Weapon::sRecordId)
                {
                    const auto& data=held.get<ESM::Weapon>()->mBase->mData;
                    const bool ranged=data.mType==ESM::Weapon::MarksmanBow || data.mType==ESM::Weapon::MarksmanCrossbow
                        || data.mType==ESM::Weapon::MarksmanThrown;
                    weaponInfo["kind"]=ranged?"ranged":"melee";
                    weaponInfo["condition_current"]=held.getClass().getItemHealth(held);
                    weaponInfo["condition_max"]=data.mHealth;
                    if (data.mType==ESM::Weapon::MarksmanBow || data.mType==ESM::Weapon::MarksmanCrossbow)
                    {
                        auto ammo=inventory.getSlot(MWWorld::InventoryStore::Slot_Ammunition);
                        const int required=data.mType==ESM::Weapon::MarksmanBow?ESM::Weapon::Arrow:ESM::Weapon::Bolt;
                        const bool usable=ammo!=inventory.end() && ammo->getType()==ESM::Weapon::sRecordId
                            && ammo->get<ESM::Weapon>()->mBase->mData.mType==required;
                        weaponInfo["available"]=usable;
                        if (usable) weaponInfo["ammunition_count"]=ammo->getCellRef().getCount();
                        else weaponInfo["unavailable_reason"]="no_ammunition";
                    }
                }
                else
                {
                    weaponInfo["kind"]="tool";weaponInfo["available"]=false;weaponInfo["unavailable_reason"]="not_a_weapon";
                    if (held.getType()==ESM::Lockpick::sRecordId || held.getType()==ESM::Probe::sRecordId)
                    {
                        const bool pick=held.getType()==ESM::Lockpick::sRecordId;
                        weaponInfo["tool_type"]=pick?"lockpick":"probe";
                        weaponInfo["uses_remaining"]=held.getClass().getItemHealth(held);
                        weaponInfo["quality"]=pick?held.get<ESM::Lockpick>()->mBase->mData.mQuality
                            :held.get<ESM::Probe>()->mBase->mData.mQuality;
                    }
                }
            }
            if (held.isEmpty() || held.getType()==ESM::Weapon::sRecordId)
                weaponInfo["reach_m"]=MWMechanics::getMeleeWeaponReach(actor,held)/70.f;
            out["weapon_info"]=weaponInfo;
        }
        if (wm->isAllowed(MWGui::GW_Magic))
        {
            auto enchanted=inventory.getSelectedEnchantItem();
            if (enchanted!=inventory.end())
            {
                const auto id=enchanted->getClass().getEnchantment(*enchanted);
                if (!id.empty())
                {
                    const auto* enchantment=MWBase::Environment::get().getESMStore()->get<ESM::Enchantment>().find(id);
                    const bool once=enchantment->mData.mType==ESM::Enchantment::CastOnce;
                    const int cost=MWMechanics::getEffectiveEnchantmentCastCost(*enchantment,actor);
                    const int capacity=MWMechanics::getEnchantmentCharge(*enchantment);
                    const float raw=enchanted->getCellRef().getEnchantmentCharge();
                    const float charge=raw<0?static_cast<float>(capacity):raw;
                    castable["kind"]=once?"scroll":"enchantment";
                    castable["name"]=std::string(enchanted->getClass().getName(*enchanted));
                    castable["cost"]=once?0:cost;castable["success_chance"]=100;
                    castable["count"]=enchanted->getCellRef().getCount();
                    castable["available"]=once || charge>=cost;
                    if (!once)
                    {
                        castable["charge_current"]=charge;castable["charge_max"]=capacity;
                        if (charge<cost) castable["unavailable_reason"]="insufficient_charge";
                    }
                }
            }
            else if (!wm->getSelectedSpell().empty()) castable=spellInfo(state,wm->getSelectedSpell());
            out["castable"]=castable;
        }
        return out;
    }
    inline sol::table reach(sol::this_state state,const LObject& object)
    {
        sol::table out(sol::state_view(state),sol::create);
        const auto target=object.ptr();
        const auto actor=player();
        if (!target.getClass().isActor()) return out;
        const float height=std::abs(actor.getRefData().getPosition().pos[2]-target.getRefData().getPosition().pos[2]);
        const float distance=MWMechanics::getDistanceToBounds(actor,target);
        const auto held=weapon(actor);
        if (held.isEmpty() || held.getType()==ESM::Weapon::sRecordId)
        {
            const float reach=MWMechanics::getMeleeWeaponReach(actor,held);
            out["melee_in_reach"]=height<reach && distance<reach;
            out["melee_margin_m"]=(reach-std::max(height,distance))/70.f;
        }
        const auto& store=MWBase::Environment::get().getESMStore()->get<ESM::GameSetting>();
        const float touch=store.find("fCombatDistance")->mValue.getFloat();
        out["touch_in_reach"]=height<touch && distance<touch;
        out["touch_margin_m"]=(touch-std::max(height,distance))/70.f;
        return out;
    }
}
