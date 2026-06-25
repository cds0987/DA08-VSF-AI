<script setup lang="ts">
// Thanh header mỏng của khu main: neo các action góc phải (hiện có chuông thông báo) để
// chúng không còn "trôi nổi". Overlay ở đỉnh <main> (main là `relative`) — nền blur trong
// suốt nhẹ để nội dung chat cuộn bên dưới vẫn thấy, không chiếm chỗ layout (page là h-dvh).
// Slot mặc định để sau thêm action mà không phải sửa layout.
</script>

<template>
  <header
    class="absolute inset-x-0 top-0 z-30 flex h-[52px] items-center justify-end gap-2 bg-background/60 px-4 backdrop-blur-md"
  >
    <slot>
      <NotificationCenter />
    </slot>
  </header>
</template>
