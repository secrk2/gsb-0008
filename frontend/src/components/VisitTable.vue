<template>
  <div class="table-scroll">
    <el-table :data="visits" size="small" :empty-text="emptyText" style="width:100%">
      <el-table-column v-if="showSite" prop="site_name" label="中心" min-width="150" />
      <el-table-column label="受试者" min-width="170">
        <template #default="{ row }">
          <div style="font-weight:600">{{ row.masked_name }}</div>
          <div style="font-size:11px; color:var(--ink-3)">{{ row.screening_no }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="visit_no" label="访视" width="70" />
      <el-table-column prop="name" label="名称" min-width="110" />
      <el-table-column label="计划日期" width="110">
        <template #default="{ row }">
          <span class="num-mono">{{ fmtDate(row.planned_date) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="130">
        <template #default="{ row }">
          <span :class="['visit-chip', row.visit_state]">
            <span v-if="row.visit_state === 'due_today'">●</span>
            {{ row.visit_state_label }}
            <span v-if="row.visit_state === 'overdue' || row.visit_state === 'out_of_window'">
              {{ Math.abs(row.days_offset) }}天
            </span>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <router-link :to="`/subjects/${row.subject_id}`"
                       style="color:var(--brand-550); font-size:12px; white-space:nowrap">
            受试者链路 →
          </router-link>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
defineProps({
  visits: { type: Array, default: () => [] },
  showSite: { type: Boolean, default: false },
  emphasize: { type: String, default: '' },
  emptyText: { type: String, default: '暂无数据' },
})
function fmtDate(d) { return d ? d.slice(0, 10) : '—' }
</script>
